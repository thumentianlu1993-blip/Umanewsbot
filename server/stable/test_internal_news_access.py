from __future__ import annotations

import importlib
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from stable.models import (
    ArticleTranslationStatus,
    AutomationStatus,
    NewsArticle,
    NotificationChannel,
    NotificationType,
    PushLog,
    PushTarget,
    QQPushDelivery,
    QQPushDeliveryStatus,
    RacingRegion,
    ReviewMode,
    SourceLanguage,
    SourceMode,
    SourceSite,
    WorkflowStatus,
)


User = get_user_model()
INTERNAL_BLOCK_REASON = "internal_only_distribution_blocked"
CONTROLS_MODULE = "stable.services.internal_controls"


def create_article(source_article_id: str, **overrides) -> NewsArticle:
    values = {
        "source_site": SourceSite.NETKEIBA,
        "source_mode": SourceMode.LATEST,
        "source_article_id": source_article_id,
        "title_ja": "内部测试原文标题",
        "body_ja_raw": "内部测试原文正文。",
        "body_ja_normalized": "内部测试原文正文。",
        "translated_title_zh": "内部测试译文标题",
        "translated_body_zh": "内部测试译文正文。",
        "title_zh": "内部测试中文标题",
        "summary_zh": "内部测试中文摘要",
        "body_zh": "内部测试中文正文。",
        "published_at": timezone.now(),
        "source_url": f"https://example.test/news/{source_article_id}",
        "racing_region": RacingRegion.JAPAN,
        "source_language": SourceLanguage.JAPANESE,
    }
    values.update(overrides)
    return NewsArticle.objects.create(**values)


class InternalControlsContractMixin:
    def require_control(self, name: str):
        try:
            module = importlib.import_module(CONTROLS_MODULE)
        except ModuleNotFoundError:
            self.fail(
                f"{CONTROLS_MODULE} must exist and expose the shared internal-only controls"
            )
        control = getattr(module, name, None)
        self.assertTrue(
            callable(control),
            f"{CONTROLS_MODULE}.{name} must be callable",
        )
        return control


class InternalAccessSettingsTests(InternalControlsContractMixin, SimpleTestCase):
    def test_internal_site_mode_defaults_to_enabled(self):
        self.assertTrue(
            hasattr(settings, "SITE_INTERNAL_ONLY_ENABLED"),
            "SITE_INTERNAL_ONLY_ENABLED must be an explicit setting",
        )
        self.assertIs(settings.SITE_INTERNAL_ONLY_ENABLED, True)

    def test_external_ai_processing_defaults_to_disabled(self):
        self.assertTrue(
            hasattr(settings, "NEWS_EXTERNAL_AI_PROCESSING_ENABLED"),
            "NEWS_EXTERNAL_AI_PROCESSING_ENABLED must be an explicit setting",
        )
        self.assertIs(settings.NEWS_EXTERNAL_AI_PROCESSING_ENABLED, False)

    def test_private_oss_media_defaults_to_disabled(self):
        self.assertTrue(
            hasattr(settings, "OSS_PRIVATE_MEDIA_ENABLED"),
            "OSS_PRIVATE_MEDIA_ENABLED must be an explicit setting",
        )
        self.assertIs(settings.OSS_PRIVATE_MEDIA_ENABLED, False)

    def test_internal_middleware_is_after_authentication_middleware(self):
        middleware = list(settings.MIDDLEWARE)
        expected = "stable.middleware.InternalSiteOnlyMiddleware"
        self.assertIn(expected, middleware)
        self.assertGreater(
            middleware.index(expected),
            middleware.index("django.contrib.auth.middleware.AuthenticationMiddleware"),
        )

    @override_settings(SITE_INTERNAL_ONLY_ENABLED=True)
    def test_distribution_blocker_shared_interface(self):
        blocker = self.require_control("external_news_distribution_blocker")
        self.assertEqual(blocker(), INTERNAL_BLOCK_REASON)

    @override_settings(SITE_INTERNAL_ONLY_ENABLED=False)
    def test_distribution_blocker_is_inactive_when_internal_mode_is_off(self):
        blocker = self.require_control("external_news_distribution_blocker")
        self.assertIsNone(blocker())

    @override_settings(NEWS_EXTERNAL_AI_PROCESSING_ENABLED=False)
    def test_external_ai_policy_allows_only_local_or_dummy_providers(self):
        allowed = self.require_control("external_ai_processing_allowed")
        for provider in ("siliconflow", "openai", "openai-compatible"):
            with self.subTest(provider=provider):
                self.assertFalse(allowed(provider))
        for provider in ("local", "dummy", "fallback"):
            with self.subTest(provider=provider):
                self.assertTrue(allowed(provider))

    @override_settings(NEWS_EXTERNAL_AI_PROCESSING_ENABLED=True)
    def test_external_ai_policy_allows_remote_provider_only_when_explicitly_enabled(self):
        allowed = self.require_control("external_ai_processing_allowed")
        self.assertTrue(allowed("siliconflow"))


@override_settings(SITE_INTERNAL_ONLY_ENABLED=True)
class InternalAccessWebTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(
            username="internal-staff",
            email="internal@example.test",
            password="test-password",
            is_staff=True,
        )

    def test_anonymous_html_business_routes_redirect_to_login(self):
        for path in ("/", "/races/", "/horses/", "/admin/"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 302)
                location = urlparse(response["Location"])
                self.assertEqual(location.path, settings.LOGIN_URL)
                next_value = parse_qs(location.query).get("next", [""])[0]
                self.assertTrue(next_value.startswith(path))

    def test_authenticated_user_can_reach_html_business_routes(self):
        self.client.force_login(self.staff)
        for path in ("/", "/races/", "/horses/", "/admin/"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)

    def test_anonymous_api_returns_json_401_without_article_fields(self):
        response = self.client.get("/api/articles/")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response["Content-Type"].split(";")[0], "application/json")
        self.assertEqual(response.json(), {"detail": "authentication_required"})
        serialized = response.content.decode("utf-8")
        for forbidden in ("title_ja", "body_ja_raw", "translated_body_zh", "source_url"):
            self.assertNotIn(forbidden, serialized)

    def test_authenticated_staff_can_reach_api(self):
        self.client.force_login(self.staff)

        response = self.client.get("/api/articles/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"results": []})

    def test_login_and_django_admin_login_are_exempt_without_redirect_loop(self):
        django_admin_login = f"{settings.DJANGO_ADMIN_URL.rstrip('/')}/login/"
        for path in (settings.LOGIN_URL, django_admin_login):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)

    def test_logout_path_reaches_logout_view_instead_of_internal_gate(self):
        response = self.client.get("/admin/logout/")

        if response.status_code == 302:
            self.assertEqual(urlparse(response["Location"]).path, settings.LOGIN_URL)
            self.assertNotIn("next=", response["Location"])
        else:
            self.assertIn(response.status_code, {200, 405})

    def test_healthcheck_remains_anonymous_json_200(self):
        response = self.client.get("/healthz/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_static_prefix_is_exempt_even_when_asset_is_missing(self):
        response = self.client.get("/static/stable/internal-only-missing.css")

        self.assertEqual(response.status_code, 404)
        self.assertNotIn("Location", response)

    def test_robots_disallows_all_anonymous_crawlers(self):
        response = self.client.get("/robots.txt")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"].split(";")[0], "text/plain")
        self.assertEqual(response.content.decode("utf-8"), "User-agent: *\nDisallow: /\n")

    def test_anonymous_sitemap_redirects_without_returning_url_inventory(self):
        response = self.client.get("/sitemap.xml")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(urlparse(response["Location"]).path, settings.LOGIN_URL)
        self.assertNotIn("<loc>", response.content.decode("utf-8", errors="ignore"))

    def test_authenticated_sitemap_remains_available_for_internal_acceptance(self):
        self.client.force_login(self.staff)

        response = self.client.get("/sitemap.xml")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"].split(";")[0], "application/xml")

    def test_login_next_is_always_a_local_path_even_if_query_contains_external_url(self):
        response = self.client.get("/?return=https://evil.example/outside")

        self.assertEqual(response.status_code, 302)
        location = urlparse(response["Location"])
        next_value = parse_qs(location.query)["next"][0]
        parsed_next = urlparse(next_value)
        self.assertEqual(parsed_next.netloc, "")
        self.assertTrue(parsed_next.path.startswith("/"))

    @override_settings(SITE_INTERNAL_ONLY_ENABLED=False)
    def test_explicitly_disabled_mode_preserves_legacy_anonymous_html(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)


class ProtectedLocalMediaTests(TestCase):
    def setUp(self):
        self.temporary_root = tempfile.TemporaryDirectory()
        self.media_root = Path(self.temporary_root.name)
        (self.media_root / "nested").mkdir()
        (self.media_root / "nested" / "sample.txt").write_text(
            "internal-media-content",
            encoding="utf-8",
        )
        (self.media_root / "directory").mkdir()
        self.outside_file = self.media_root.parent / "outside-internal-media-secret.txt"
        self.outside_file.write_text("outside-secret", encoding="utf-8")
        (self.media_root / "escape-link.txt").symlink_to(self.outside_file)
        self.staff = User.objects.create_user(
            username="media-staff",
            password="test-password",
            is_staff=True,
        )
        self.authenticated = Client()
        self.authenticated.force_login(self.staff)

    def tearDown(self):
        self.outside_file.unlink(missing_ok=True)
        self.temporary_root.cleanup()

    def media_settings(self, **overrides):
        values = {
            "SITE_INTERNAL_ONLY_ENABLED": True,
            "MEDIA_STORAGE_BACKEND": "local",
            "MEDIA_ROOT": self.media_root,
        }
        values.update(overrides)
        return self.settings(**values)

    def test_anonymous_local_media_redirects_without_file_bytes(self):
        with self.media_settings():
            response = self.client.get("/media/nested/sample.txt")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(urlparse(response["Location"]).path, settings.LOGIN_URL)
        self.assertNotIn(b"internal-media-content", response.content)

    def test_authenticated_local_media_returns_file_response_in_development(self):
        with self.media_settings(DEBUG=True):
            response = self.authenticated.get("/media/nested/sample.txt")

        self.assertEqual(response.status_code, 200)
        if response.has_header("X-Accel-Redirect"):
            self.assertEqual(
                response["X-Accel-Redirect"],
                "/protected-media/nested/sample.txt",
            )
        else:
            self.assertTrue(response.streaming)
            self.assertEqual(b"".join(response.streaming_content), b"internal-media-content")

    def test_authenticated_local_media_uses_x_accel_redirect_in_production_shape(self):
        with self.media_settings(DEBUG=False):
            response = self.authenticated.get(
                "/media/nested/sample.txt",
                secure=True,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["X-Accel-Redirect"],
            "/protected-media/nested/sample.txt",
        )
        self.assertNotIn(b"internal-media-content", response.content)

    def test_authenticated_media_rejects_traversal_absolute_symlink_and_directory(self):
        paths = (
            "/media/%2E%2E/outside-internal-media-secret.txt",
            "/media/%2Fetc%2Fpasswd",
            "/media/escape-link.txt",
            "/media/directory/",
            "/media/missing.txt",
        )
        with self.media_settings():
            for path in paths:
                with self.subTest(path=path):
                    response = self.authenticated.get(path)
                    self.assertIn(response.status_code, {400, 404})
                    if not response.streaming:
                        self.assertNotIn(b"outside-secret", response.content)


class NginxProtectedMediaShapeTests(SimpleTestCase):
    def test_nginx_has_only_internal_protected_media_location(self):
        config_path = Path(settings.BASE_DIR).parent / "deploy" / "nginx" / "nginx.conf"
        config = config_path.read_text(encoding="utf-8")

        self.assertNotRegex(
            config,
            r"location\s+/media/\s*\{[^}]*\balias\b",
        )
        self.assertRegex(
            config,
            r"location\s+/protected-media/\s*\{[^}]*\binternal\s*;",
        )


class PrivateOSSMediaTests(InternalControlsContractMixin, SimpleTestCase):
    @override_settings(
        SITE_INTERNAL_ONLY_ENABLED=True,
        MEDIA_STORAGE_BACKEND="local",
    )
    def test_internal_media_preflight_accepts_local_backend(self):
        preflight = self.require_control("validate_internal_media_configuration")
        self.assertIsNone(preflight())

    @override_settings(
        SITE_INTERNAL_ONLY_ENABLED=True,
        MEDIA_STORAGE_BACKEND="oss",
        OSS_PRIVATE_MEDIA_ENABLED=False,
        OSS_BUCKET_NAME="internal-bucket",
        OSS_ENDPOINT="https://oss.example.test",
    )
    def test_internal_media_preflight_rejects_oss_without_private_mode(self):
        preflight = self.require_control("validate_internal_media_configuration")
        with self.assertRaisesRegex(ImproperlyConfigured, "private"):
            preflight()

    @override_settings(
        SITE_INTERNAL_ONLY_ENABLED=True,
        MEDIA_STORAGE_BACKEND="oss",
        OSS_PRIVATE_MEDIA_ENABLED=True,
        OSS_PRIVATE_MEDIA_URL_TTL_SECONDS=3600,
        OSS_BUCKET_NAME="internal-bucket",
        OSS_ENDPOINT="https://oss.example.test",
        OSS_ACCESS_KEY_ID="access-key",
        OSS_ACCESS_KEY_SECRET="secret-key",
    )
    def test_internal_media_preflight_rejects_long_lived_oss_urls(self):
        preflight = self.require_control("validate_internal_media_configuration")
        with self.assertRaisesRegex(ImproperlyConfigured, "TTL|ttl"):
            preflight()

    @override_settings(
        SITE_INTERNAL_ONLY_ENABLED=True,
        MEDIA_STORAGE_BACKEND="oss",
        OSS_PRIVATE_MEDIA_ENABLED=True,
        OSS_PRIVATE_MEDIA_URL_TTL_SECONDS=300,
        OSS_BUCKET_NAME="internal-bucket",
        OSS_ENDPOINT="https://oss.example.test",
        OSS_ACCESS_KEY_ID="access-key",
        OSS_ACCESS_KEY_SECRET="secret-key",
        OSS_MEDIA_PREFIX="media",
    )
    def test_private_oss_storage_returns_short_lived_signed_url(self):
        from stable.services.oss_storage import AliyunOSSStorage

        signed_url = (
            "https://internal-bucket.oss.example.test/media/news/file.jpg"
            "?Expires=300&Signature=signed-value"
        )
        with patch("stable.services.oss_storage.oss2.Bucket") as bucket_class:
            bucket_class.return_value.sign_url.return_value = signed_url
            storage = AliyunOSSStorage()
            result = storage.url("news/file.jpg")

        bucket_class.return_value.sign_url.assert_called_once_with(
            "GET",
            "media/news/file.jpg",
            300,
        )
        self.assertEqual(result, signed_url)
        self.assertNotIn("access-key", result)
        self.assertNotIn("secret-key", result)


@override_settings(
    SITE_INTERNAL_ONLY_ENABLED=True,
    QQ_PUSH_ENABLED=True,
    QQ_PUSH_SCOPE="all_public",
    SITE_URL="https://internal.example.test",
)
class ExternalDistributionBlockerTests(InternalControlsContractMixin, TestCase):
    def setUp(self):
        self.article = create_article(
            "distribution-article",
            workflow_status=WorkflowStatus.PUBLISHED,
            published_to_web_at=timezone.now(),
        )
        self.target = PushTarget.objects.create(
            name="blocked-external-group",
            group_id="internal-test-group",
            is_active=True,
            allowed_regions=[RacingRegion.JAPAN],
            push_scope="all_public",
        )

    def test_qq_eligibility_is_blocked_with_stable_reason(self):
        from stable.services.qq_auto_push import should_push_news_to_qq

        result = should_push_news_to_qq(
            self.article,
            scope="all_public",
            target=self.target,
        )

        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, INTERNAL_BLOCK_REASON)

    def test_delivery_creation_is_blocked_before_database_write(self):
        from stable.services.qq_auto_push import ensure_qq_push_deliveries

        deliveries = ensure_qq_push_deliveries(self.article, [self.target])

        self.assertEqual(deliveries, [])
        self.assertEqual(QQPushDelivery.objects.count(), 0)

    def test_single_article_task_blocks_before_delivery_or_dispatch(self):
        from stable.tasks import qq_auto_push_article_task

        with patch("stable.tasks.qq_push_delivery_task.delay") as delay:
            result = qq_auto_push_article_task.run(self.article.id)

        self.assertTrue(result.get("skipped"))
        self.assertEqual(result.get("reason"), INTERNAL_BLOCK_REASON)
        self.assertEqual(QQPushDelivery.objects.count(), 0)
        delay.assert_not_called()

    def test_existing_pending_delivery_is_blocked_before_onebot_or_url_check(self):
        from stable.services.qq_auto_push import process_qq_push_delivery

        delivery = QQPushDelivery.objects.create(
            article=self.article,
            target=self.target,
            status=QQPushDeliveryStatus.PENDING,
        )
        with (
            patch(
                "stable.services.qq_auto_push.BotPusher.is_online",
                return_value=(True, ""),
            ) as online,
            patch(
                "stable.services.qq_auto_push.is_public_url_accessible",
                return_value=(True, ""),
            ) as url_check,
            patch(
                "stable.services.qq_auto_push.BotPusher.send_group_message",
                return_value={"status": "ok"},
            ) as send_group,
        ):
            result = process_qq_push_delivery(delivery)

        result.refresh_from_db()
        self.assertEqual(result.status, QQPushDeliveryStatus.SKIPPED)
        self.assertEqual(result.last_error, INTERNAL_BLOCK_REASON)
        online.assert_not_called()
        url_check.assert_not_called()
        send_group.assert_not_called()

    def test_legacy_pushlog_path_blocks_before_log_and_onebot(self):
        from stable.services.pushing import push_article_to_targets

        with patch(
            "stable.services.pushing.BotPusher.send_group_message",
            return_value={"status": "ok"},
        ) as send_group:
            logs = push_article_to_targets(self.article, [self.target])

        self.assertEqual(logs, [])
        self.assertEqual(PushLog.objects.count(), 0)
        send_group.assert_not_called()

    def test_public_url_check_is_blocked_before_http(self):
        from stable.services.qq_auto_push import is_public_url_accessible

        response = MagicMock(status_code=200)
        with patch(
            "stable.services.qq_auto_push.requests.get",
            return_value=response,
        ) as request_get:
            result = is_public_url_accessible(
                "https://internal.example.test/news/123/"
            )

        self.assertEqual(result, (False, INTERNAL_BLOCK_REASON))
        request_get.assert_not_called()

    def test_historical_delivery_states_are_not_rewritten_or_requeued(self):
        from stable.tasks import qq_auto_push_article_task

        sent = QQPushDelivery.objects.create(
            article=self.article,
            target=self.target,
            status=QQPushDeliveryStatus.SENT,
            attempt_count=1,
            message_id="historic-message",
            sent_at=timezone.now(),
        )
        failed_article = create_article(
            "distribution-failed-history",
            workflow_status=WorkflowStatus.PUBLISHED,
            published_to_web_at=timezone.now(),
        )
        failed = QQPushDelivery.objects.create(
            article=failed_article,
            target=self.target,
            status=QQPushDeliveryStatus.FAILED,
            attempt_count=3,
            max_attempts=3,
            last_error="historic-failure",
        )
        sent_snapshot = (
            sent.status,
            sent.attempt_count,
            sent.message_id,
            sent.sent_at,
        )
        failed_snapshot = (
            failed.status,
            failed.attempt_count,
            failed.last_error,
        )

        with patch("stable.tasks.qq_push_delivery_task.delay") as delay:
            sent_result = qq_auto_push_article_task.run(self.article.id)
            failed_result = qq_auto_push_article_task.run(failed_article.id)

        sent.refresh_from_db()
        failed.refresh_from_db()
        self.assertEqual(
            (sent.status, sent.attempt_count, sent.message_id, sent.sent_at),
            sent_snapshot,
        )
        self.assertEqual(
            (failed.status, failed.attempt_count, failed.last_error),
            failed_snapshot,
        )
        self.assertEqual(sent_result.get("reason"), INTERNAL_BLOCK_REASON)
        self.assertEqual(failed_result.get("reason"), INTERNAL_BLOCK_REASON)
        delay.assert_not_called()


@override_settings(SITE_INTERNAL_ONLY_ENABLED=True)
class InternalNotificationSanitizerTests(InternalControlsContractMixin, TestCase):
    safe_payload = {
        "task": "translate_article",
        "error_category": "upstream_timeout",
        "count": 2,
        "occurred_at": "2026-07-19T12:00:00Z",
        "article_id": 42,
    }
    forbidden_payload = {
        "title": "DO-NOT-SEND-TITLE",
        "body": "DO-NOT-SEND-ORIGINAL-BODY",
        "translated_body_zh": "DO-NOT-SEND-TRANSLATION",
        "summary": "DO-NOT-SEND-SUMMARY",
        "source_url": "https://source.example.test/private-article",
    }

    def assert_no_forbidden_content(self, value) -> None:
        serialized = json.dumps(value, ensure_ascii=False, default=str)
        for forbidden in self.forbidden_payload.values():
            self.assertNotIn(forbidden, serialized)

    def test_sanitizer_keeps_whitelist_and_drops_news_content(self):
        sanitizer = self.require_control("sanitize_internal_ops_notification")

        sanitized = sanitizer({**self.safe_payload, **self.forbidden_payload})

        self.assertEqual(sanitized, self.safe_payload)
        self.assert_no_forbidden_content(sanitized)

    def test_sanitizer_returns_none_when_no_safe_summary_remains(self):
        sanitizer = self.require_control("sanitize_internal_ops_notification")

        sanitized = sanitizer(dict(self.forbidden_payload))

        self.assertIsNone(sanitized)

    @override_settings(
        AUTOMATION_ENABLE_EMAIL=True,
        AUTOMATION_NOTIFY_EMAILS=["ops@example.test"],
    )
    def test_automation_email_receives_only_sanitized_payload(self):
        from stable.services.notifications import send_automation_notification

        with patch("stable.services.notifications.send_mail") as send_mail:
            send_automation_notification(
                NotificationType.REWRITE_FAILED,
                {**self.safe_payload, **self.forbidden_payload},
                channels=[NotificationChannel.EMAIL],
            )

        send_mail.assert_called_once()
        self.assert_no_forbidden_content(send_mail.call_args)
        summaries = list(self._notification_summaries())
        self.assert_no_forbidden_content(summaries)

    @override_settings(
        AUTOMATION_ENABLE_EMAIL=True,
        AUTOMATION_NOTIFY_EMAILS=["ops@example.test"],
    )
    def test_unsafe_only_automation_email_is_not_sent(self):
        from stable.services.notifications import send_automation_notification

        with patch("stable.services.notifications.send_mail") as send_mail:
            send_automation_notification(
                NotificationType.REWRITE_FAILED,
                dict(self.forbidden_payload),
                channels=[NotificationChannel.EMAIL],
            )

        send_mail.assert_not_called()
        self.assert_no_forbidden_content(list(self._notification_summaries()))

    @override_settings(
        MULTIREGION_OPS_NOTIFICATIONS_ENABLED=True,
        MULTIREGION_ROLLBACK_DISABLE_OPS_NOTIFICATIONS=False,
        MULTIREGION_OPS_NOTIFICATION_COOLDOWN_MINUTES=0,
        MULTIREGION_OPS_NOTIFICATION_QQ_GROUP_ID="ops-group",
        MULTIREGION_OPS_NOTIFICATION_EMAILS=["ops@example.test"],
    )
    def test_ops_email_and_qq_receive_only_sanitized_payload(self):
        from stable.services.ops_notifications import send_ops_notification

        with (
            patch(
                "stable.services.ops_notifications.BotPusher.send_group_message"
            ) as send_group,
            patch("stable.services.ops_notifications.send_mail") as send_mail,
        ):
            send_ops_notification(
                notification_type=NotificationType.OPS_ANOMALY,
                title="stable_ops_failure",
                payload={**self.safe_payload, **self.forbidden_payload},
            )

        send_group.assert_called_once()
        send_mail.assert_called_once()
        self.assert_no_forbidden_content(send_group.call_args)
        self.assert_no_forbidden_content(send_mail.call_args)
        self.assert_no_forbidden_content(list(self._notification_summaries()))

    @override_settings(
        TRANSLATION_FAILURE_EMAIL_ENABLED=True,
        TRANSLATION_FAILURE_NOTIFY_EMAILS=["ops@example.test"],
    )
    def test_translation_failure_email_does_not_include_article_content_or_source_url(self):
        from stable.services.translation_recovery import (
            notify_terminal_translation_failure,
        )

        article = create_article(
            "notification-translation-failure",
            title_ja=self.forbidden_payload["title"],
            title_zh=self.forbidden_payload["title"],
            body_ja_raw=self.forbidden_payload["body"],
            body_ja_normalized=self.forbidden_payload["body"],
            translated_body_zh=self.forbidden_payload["translated_body_zh"],
            summary_zh=self.forbidden_payload["summary"],
            source_url=self.forbidden_payload["source_url"],
            translation_status=ArticleTranslationStatus.FAILED,
            translation_error_category="upstream_timeout",
            translation_error_message="stable_timeout",
            translation_retry_count=3,
        )

        with patch("stable.services.translation_recovery.send_mail") as send_mail:
            notify_terminal_translation_failure(article)

        send_mail.assert_called_once()
        self.assert_no_forbidden_content(send_mail.call_args)
        self.assert_no_forbidden_content(list(self._notification_summaries()))

    @staticmethod
    def _notification_summaries():
        from stable.models import NotificationLog

        return NotificationLog.objects.values_list("payload_summary", flat=True)


@override_settings(
    NEWS_EXTERNAL_AI_PROCESSING_ENABLED=False,
    AUTOMATION_ENABLED=False,
)
class ExternalAIProcessingTests(InternalControlsContractMixin, TestCase):
    def remote_client(self, payload: dict):
        client = MagicMock()
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps(payload, ensure_ascii=False)
                    ),
                    finish_reason="stop",
                )
            ],
            usage=None,
        )
        return client

    def test_remote_translation_is_blocked_before_client_construction_or_call(self):
        from stable.tasks import translate_article_task

        article = create_article(
            "remote-translation-blocked",
            workflow_status=WorkflowStatus.PENDING_TRANSLATION,
            translation_status=ArticleTranslationStatus.PENDING,
        )
        client = self.remote_client(
            {
                "title_zh": "不应生成的远程译文",
                "body_zh": "不应生成的远程译文正文。",
                "push_summary_zh": "不应生成的远程摘要",
            }
        )
        with (
            self.settings(
                TRANSLATION_PROVIDER="siliconflow",
                SILICONFLOW_API_KEY="test-key",
                TRANSLATION_MAX_ATTEMPTS=1,
            ),
            patch(
                "stable.services.translation.OpenAI",
                return_value=client,
            ) as remote_constructor,
        ):
            result = translate_article_task.run(article.id)

        article.refresh_from_db()
        remote_constructor.assert_not_called()
        client.chat.completions.create.assert_not_called()
        self.assertEqual(result["reason"], "external_translation_disabled")
        self.assertFalse(result["translated"])
        self.assertEqual(
            article.translation_status,
            ArticleTranslationStatus.PENDING,
        )
        self.assertEqual(
            article.workflow_status,
            WorkflowStatus.PENDING_TRANSLATION,
        )
        self.assertEqual(article.translation_runs.count(), 0)
        self.assertEqual(article.body_ja_raw, "内部测试原文正文。")

    def test_dummy_translation_remains_available_with_external_ai_disabled(self):
        from stable.tasks import translate_article_task

        article = create_article(
            "dummy-translation-allowed",
            workflow_status=WorkflowStatus.PENDING_TRANSLATION,
            translation_status=ArticleTranslationStatus.PENDING,
        )
        with (
            self.settings(TRANSLATION_PROVIDER="dummy"),
            patch("stable.services.translation.OpenAI") as remote_constructor,
        ):
            result = translate_article_task.run(article.id)

        article.refresh_from_db()
        self.assertTrue(result["translated"])
        self.assertEqual(
            article.translation_status,
            ArticleTranslationStatus.TRANSLATED,
        )
        self.assertEqual(article.translation_runs.count(), 1)
        self.assertEqual(
            article.translation_runs.get().provider_name,
            "dummy",
        )
        remote_constructor.assert_not_called()

    def test_remote_rewrite_is_blocked_before_client_construction_or_call(self):
        from stable.tasks import rewrite_article_task

        article = create_article(
            "remote-rewrite-blocked",
            review_mode=ReviewMode.AUTO,
            automation_status=AutomationStatus.REWRITE_READY,
        )
        client = self.remote_client(
            {
                "rewrite_title_zh": "不应生成的远程改写标题",
                "rewrite_summary_zh": "不应生成的远程改写摘要",
                "rewrite_body_zh": "不应生成的远程改写正文。",
                "rewrite_confidence": 90,
            }
        )
        with (
            self.settings(
                REWRITE_PROVIDER="siliconflow",
                SILICONFLOW_API_KEY="test-key",
            ),
            patch(
                "stable.services.rewriting.OpenAI",
                return_value=client,
            ) as remote_constructor,
        ):
            result = rewrite_article_task.run(article.id)

        article.refresh_from_db()
        remote_constructor.assert_not_called()
        client.chat.completions.create.assert_not_called()
        self.assertEqual(result["reason"], "external_rewrite_disabled")
        self.assertFalse(result["rewritten"])
        self.assertEqual(
            article.automation_status,
            AutomationStatus.REWRITE_READY,
        )
        self.assertEqual(article.rewrite_body_zh, "")

    def test_local_fallback_rewrite_remains_available_with_external_ai_disabled(self):
        from stable.tasks import rewrite_article_task

        article = create_article(
            "fallback-rewrite-allowed",
            review_mode=ReviewMode.AUTO,
            automation_status=AutomationStatus.REWRITE_READY,
        )
        with (
            self.settings(
                REWRITE_PROVIDER="fallback",
                TRANSLATION_PROVIDER="dummy",
            ),
            patch("stable.services.rewriting.OpenAI") as remote_constructor,
        ):
            result = rewrite_article_task.run(article.id)

        article.refresh_from_db()
        self.assertTrue(result["rewritten"])
        self.assertEqual(
            article.automation_status,
            AutomationStatus.REWRITTEN,
        )
        self.assertTrue(article.rewrite_body_zh)
        remote_constructor.assert_not_called()
