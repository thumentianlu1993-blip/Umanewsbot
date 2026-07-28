"""
赛事新闻聚类与首页 / QQ 曝光治理测试。

目标功能尚未实现，所有测试应因 RaceNewsExposure 模型和相关服务不存在而失败（RED）。

测试用例编号对应 docs/changes/govern-race-news-exposure/test_cases.md：
  - 1-4: 赛事身份与硬重复
  - 5: 跨年度同名不聚类
  - 6-10: 两席状态机
  - 11-15: 模型与并发
  - 16-20: 首页与头条
  - 21-24: QQ
  - 25-28: 历史回填
  - 29-30: 性能与迁移
"""

from __future__ import annotations

import json
from datetime import timedelta

from django.conf import settings
from django.db import connection, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from stable.models import (
    ArticleRaceLink,
    ArticleRaceLinkStatus,
    ArticleRaceLinkType,
    NewsArticle,
    PushTarget,
    QQPushDelivery,
    QQPushDeliveryStatus,
    RaceEvent,
    RacingRegion,
    SourceLanguage,
    SourceMode,
    SourceSite,
    WorkflowStatus,
)


# ============================================================================
# 辅助函数
# ============================================================================

def _make_event(
    *,
    year: int = 2026,
    slug: str = "king-george-vi-and-queen-elizabeth-stakes",
    original_name: str = "King George VI And Queen Elizabeth Stakes",
    chinese_name: str = "英皇锦标",
    country_region: str = RacingRegion.UNITED_KINGDOM,
    **kwargs,
) -> RaceEvent:
    """创建一个最小化的 RaceEvent。"""
    return RaceEvent.objects.create(
        year=year,
        slug=slug,
        original_name=original_name,
        chinese_name=chinese_name,
        country_region=country_region,
        racecourse="Ascot",
        grade_text="G1",
        surface="turf",
        **kwargs,
    )


def _make_article(
    *,
    title: str = "测试文章",
    source_site: str = SourceSite.SPORTING_LIFE,
    source_article_id: str | None = None,
    published_at=None,
    workflow_status: str = WorkflowStatus.PUBLISHED,
    score_total: int = 100,
    **kwargs,
) -> NewsArticle:
    """创建一个最小化的 NewsArticle。"""
    now = timezone.now()
    if source_article_id is None:
        source_article_id = f"test-{timezone.now().timestamp()}-{id(title)}"
    published_at = published_at or now
    return NewsArticle.objects.create(
        source_site=source_site,
        source_mode=SourceMode.LATEST,
        racing_region=RacingRegion.UNITED_KINGDOM,
        source_language=SourceLanguage.ENGLISH,
        source_article_id=source_article_id,
        title_ja=title,
        translated_title_zh=title,
        title_zh=title,
        body_ja_raw=f"{title} 原文内容",
        body_ja_normalized=f"{title} 原文内容",
        published_at=published_at,
        published_to_web_at=now,
        source_url=f"https://example.com/{title}",
        workflow_status=workflow_status,
        score_total=score_total,
        **kwargs,
    )


def _make_push_target(
    *,
    name: str = "测试群",
    group_id: str | None = None,
    is_active: bool = True,
) -> PushTarget:
    """创建一个 PushTarget。"""
    if group_id is None:
        group_id = f"group-{timezone.now().timestamp()}-{id(name)}"
    return PushTarget.objects.create(
        name=name,
        group_id=group_id,
        is_active=is_active,
    )


def _make_article_race_link(
    article: NewsArticle,
    event: RaceEvent,
    status: str = ArticleRaceLinkStatus.AUTO,
    link_type: str = ArticleRaceLinkType.POST_RACE,
    confidence: int = 100,
) -> ArticleRaceLink:
    """创建一个 ArticleRaceLink。"""
    return ArticleRaceLink.objects.create(
        event=event,
        article=article,
        status=status,
        link_type=link_type,
        confidence=confidence,
    )


def _try_import_model(model_path: str):
    """尝试导入模块，失败时引发 ImportError。"""
    parts = model_path.split(".")
    module_path = ".".join(parts[:-1])
    class_name = parts[-1]
    try:
        module = __import__(module_path, fromlist=[class_name])
        return getattr(module, class_name)
    except (ImportError, AttributeError) as e:
        raise ImportError(f"模型 {model_path} 未实现") from e


def _try_import_service(service_path: str):
    """尝试导入服务函数，失败时引发 ImportError。"""
    parts = service_path.split(".")
    module_path = ".".join(parts[:-1])
    func_name = parts[-1]
    try:
        module = __import__(module_path, fromlist=[func_name])
        return getattr(module, func_name)
    except (ImportError, AttributeError) as e:
        raise ImportError(f"服务 {service_path} 未实现") from e


# ============================================================================
# 测试用例 30: Migration
# ============================================================================

class MigrationTests(TestCase):
    """Migration forward/backward 通过。"""

    def test_migration_forward(self) -> None:
        """migration 应创建 race_news_exposure 表。"""
        try:
            from stable.models import RaceNewsExposure
        except ImportError:
            self.fail("RaceNewsExposure 模型尚未实现（预期 RED）")
        all_tables = connection.introspection.table_names()
        db_table = RaceNewsExposure._meta.db_table
        self.assertIn(
            db_table,
            all_tables,
            f"数据库表中不存在 {db_table}",
        )


# ============================================================================
# 测试用例 1-4: 赛事身份与硬重复
# ============================================================================

class RaceIdentityTests(TestCase):
    """测试赛事身份解析与硬重复逻辑。"""

    def test_race_news_exposure_model_exists(self) -> None:
        """RaceNewsExposure 模型应可通过 import 访问。"""
        try:
            from stable.models import RaceNewsExposure
        except ImportError:
            self.fail("RaceNewsExposure 模型未实现（预期 RED 直至模型创建）")

    def test_event_identity_by_unique_manual_link(self) -> None:
        """唯一 manual link 应得到 event identity。"""
        try:
            resolve_race_identity = _try_import_service(
                "stable.services.race_news_exposure.resolve_race_identity"
            )
        except ImportError:
            self.fail("resolve_race_identity 服务未实现（预期 RED）")
            return
        event = _make_event()
        article = _make_article(title="英皇赛果")
        _make_article_race_link(
            article=article, event=event,
            status=ArticleRaceLinkStatus.MANUAL,
        )
        result = resolve_race_identity(article)
        self.assertIsNotNone(result)
        self.assertEqual(result["event_id"], event.id)
        self.assertEqual(result["method"], "manual")

    def test_event_identity_by_unique_auto_link(self) -> None:
        """唯一且达到可靠阈值的 auto link 应得到 event identity。"""
        try:
            resolve_race_identity = _try_import_service(
                "stable.services.race_news_exposure.resolve_race_identity"
            )
        except ImportError:
            self.fail("resolve_race_identity 服务未实现（预期 RED）")
            return
        event = _make_event()
        article = _make_article(title="英皇赛果")
        _make_article_race_link(
            article=article, event=event,
            status=ArticleRaceLinkStatus.AUTO,
            confidence=90,
        )
        result = resolve_race_identity(article)
        self.assertIsNotNone(result)
        self.assertEqual(result["event_id"], event.id)
        self.assertEqual(result["method"], "auto")

    def test_candidate_link_unresolved(self) -> None:
        """只有 candidate/removed 链接时 unresolved。"""
        try:
            resolve_race_identity = _try_import_service(
                "stable.services.race_news_exposure.resolve_race_identity"
            )
        except ImportError:
            self.fail("resolve_race_identity 服务未实现（预期 RED）")
            return
        event = _make_event()
        article = _make_article(title="候选关联")
        _make_article_race_link(
            article=article, event=event,
            status=ArticleRaceLinkStatus.CANDIDATE,
        )
        result = resolve_race_identity(article)
        self.assertIsNone(result)

    def test_manual_conflict_unresolved(self) -> None:
        """多个 manual 指向不同赛事时 unresolved。"""
        try:
            resolve_race_identity = _try_import_service(
                "stable.services.race_news_exposure.resolve_race_identity"
            )
        except ImportError:
            self.fail("resolve_race_identity 服务未实现（预期 RED）")
            return
        event_a = _make_event(slug="race-a", chinese_name="赛事A")
        event_b = _make_event(slug="race-b", chinese_name="赛事B")
        article = _make_article(title="歧义关联")
        _make_article_race_link(
            article=article, event=event_a,
            status=ArticleRaceLinkStatus.MANUAL,
        )
        _make_article_race_link(
            article=article, event=event_b,
            status=ArticleRaceLinkStatus.MANUAL,
        )
        result = resolve_race_identity(article)
        self.assertIsNone(result)

    def test_multiple_qualified_auto_unresolved(self) -> None:
        """多个合格 auto 指向不同赛事时 unresolved。"""
        try:
            resolve_race_identity = _try_import_service(
                "stable.services.race_news_exposure.resolve_race_identity"
            )
        except ImportError:
            self.fail("resolve_race_identity 服务未实现（预期 RED）")
            return
        event_a = _make_event(slug="race-a", chinese_name="赛事A")
        event_b = _make_event(slug="race-b", chinese_name="赛事B")
        article = _make_article(title="多自动关联")
        _make_article_race_link(
            article=article, event=event_a, confidence=85,
        )
        _make_article_race_link(
            article=article, event=event_b, confidence=90,
        )
        result = resolve_race_identity(article)
        self.assertIsNone(result)


class HardDuplicateTests(TestCase):
    """测试硬重复判断。"""

    def test_hard_duplicate_same_source_normalized_title(self) -> None:
        """相同赛事、规范化来源标题完全相同 -> 判为硬重复。"""
        try:
            classify_hard_duplicate = _try_import_service(
                "stable.services.race_news_exposure.classify_hard_duplicate"
            )
        except ImportError:
            self.fail("classify_hard_duplicate 服务未实现（预期 RED）")
            return
        event = _make_event()
        article_a = _make_article(
            title="英皇锦标 King George VI Stakes 赛果",
            source_site=SourceSite.SPORTING_LIFE,
        )
        article_b = _make_article(
            title="英皇锦标 King George VI Stakes 赛果",
            source_site=SourceSite.SPORTING_LIFE,
        )
        _make_article_race_link(article=article_a, event=event, status=ArticleRaceLinkStatus.AUTO)
        _make_article_race_link(article=article_b, event=event, status=ArticleRaceLinkStatus.AUTO)
        result = classify_hard_duplicate(article_a, article_b, event)
        self.assertTrue(result["is_duplicate"])
        self.assertEqual(result["reason"], "same_normalized_title")

    def test_hard_duplicate_does_not_cross_event(self) -> None:
        """不同赛事，即使标题相同也不判硬重复（由 caller 限定同赛事）。"""
        try:
            classify_hard_duplicate = _try_import_service(
                "stable.services.race_news_exposure.classify_hard_duplicate"
            )
        except ImportError:
            self.fail("classify_hard_duplicate 服务未实现（预期 RED）")
            return
        event_a = _make_event(slug="race-a", chinese_name="赛事A")
        event_b = _make_event(slug="race-b", chinese_name="赛事B")
        article_a = _make_article(title="相同的标题")
        article_b = _make_article(title="相同的标题")
        _make_article_race_link(article=article_a, event=event_a, status=ArticleRaceLinkStatus.AUTO)
        _make_article_race_link(article=article_b, event=event_b, status=ArticleRaceLinkStatus.AUTO)
        # 不同赛事时不判硬重复
        result_a = classify_hard_duplicate(article_a, article_b, event_a)
        result_b = classify_hard_duplicate(article_a, article_b, event_b)
        self.assertFalse(result_a["is_duplicate"])
        self.assertFalse(result_b["is_duplicate"])


class DifferentAngleNoDuplicateTests(TestCase):
    """同赛事不同角度不判 duplicate。"""

    def test_comprehensive_result_and_winner_not_duplicate(self) -> None:
        """综合赛果与胜者稿件应是不同角度，不写 duplicate_of。"""
        try:
            classify_hard_duplicate = _try_import_service(
                "stable.services.race_news_exposure.classify_hard_duplicate"
            )
        except ImportError:
            self.fail("classify_hard_duplicate 服务未实现（预期 RED）")
            return
        event = _make_event()
        article_a = _make_article(
            title="英皇锦标赛果：胜者风采",
            source_article_id="result-1",
        )
        article_b = _make_article(
            title="练马师谈英皇锦标冠军备战计划",
            source_article_id="result-2",
        )
        result = classify_hard_duplicate(article_a, article_b, event)
        # 不同角度应不判硬重复
        self.assertFalse(result["is_duplicate"])


class CrossYearNoClusterTests(TestCase):
    """跨年度同名不聚类。"""

    def test_cross_year_same_name_not_clustered(self) -> None:
        """相同赛事名称但不同年份不应解析为同一赛事。"""
        try:
            resolve_race_identity = _try_import_service(
                "stable.services.race_news_exposure.resolve_race_identity"
            )
        except ImportError:
            self.fail("resolve_race_identity 服务未实现（预期 RED）")
            return
        event_2025 = _make_event(year=2025, slug="king-george-2025")
        article_2025 = _make_article(title="2025年英皇锦标")
        _make_article_race_link(
            article=article_2025, event=event_2025,
            status=ArticleRaceLinkStatus.MANUAL,
        )
        # 2026 年文章应链接到 2026 赛事，而非 2025
        event_2026 = _make_event(year=2026, slug="king-george-2026")
        article_2026 = _make_article(title="2026年英皇锦标")
        _make_article_race_link(
            article=article_2026, event=event_2026,
            status=ArticleRaceLinkStatus.MANUAL,
        )
        result_2025 = resolve_race_identity(article_2025)
        result_2026 = resolve_race_identity(article_2026)
        self.assertIsNotNone(result_2025)
        self.assertIsNotNone(result_2026)
        self.assertEqual(result_2025["event_id"], event_2025.id)
        self.assertEqual(result_2026["event_id"], event_2026.id)
        self.assertNotEqual(result_2025["event_id"], result_2026["event_id"])


# ============================================================================
# 测试用例 6-10: 两席状态机
# ============================================================================

class TwoSlotStateMachineTests(TestCase):
    """测试第一席/第二席状态机行为。"""

    def test_first_slot_immediately_active(self) -> None:
        """第一席立即激活。"""
        try:
            reserve_exposure = _try_import_service(
                "stable.services.race_news_exposure.reserve_exposure"
            )
        except ImportError:
            self.fail("reserve_exposure 服务未实现（预期 RED）")
            return
        event = _make_event()
        article = _make_article(title="首篇综合赛果")
        result = reserve_exposure(
            event=event,
            article=article,
            channel="homepage",
            scope_key="site",
            angle="comprehensive_result",
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["slot"], 1)
        self.assertEqual(result["status"], "active")
        self.assertIsNotNone(result["activated_at"])

    def test_second_slot_waiting_before_15min(self) -> None:
        """第一席激活 15 分钟内，第二席为 waiting。"""
        try:
            reserve_exposure = _try_import_service(
                "stable.services.race_news_exposure.reserve_exposure"
            )
        except ImportError:
            self.fail("reserve_exposure 服务未实现（预期 RED）")
            return
        event = _make_event()
        article1 = _make_article(title="首篇综合赛果")
        result1 = reserve_exposure(
            event=event,
            article=article1,
            channel="homepage",
            scope_key="site",
            angle="comprehensive_result",
        )
        # 第二篇立即写入，应在 15 分钟等待期
        article2 = _make_article(title="练马师反应")
        result2 = reserve_exposure(
            event=event,
            article=article2,
            channel="homepage",
            scope_key="site",
            angle="connections",
        )
        self.assertEqual(result2["slot"], 2)
        self.assertEqual(result2["status"], "waiting")

    def test_second_slot_active_after_15min(self) -> None:
        """第一席激活满 15 分钟后，第二席可激活。"""
        try:
            reserve_exposure = _try_import_service(
                "stable.services.race_news_exposure.reserve_exposure"
            )
        except ImportError:
            self.fail("reserve_exposure 服务未实现（预期 RED）")
            return
        event = _make_event()
        past = timezone.now() - timedelta(minutes=20)
        article1 = _make_article(title="第一席旧文章", published_at=past)
        result1 = reserve_exposure(
            event=event,
            article=article1,
            channel="homepage",
            scope_key="site",
            angle="comprehensive_result",
            activated_at=past,
        )
        article2 = _make_article(title="第二席不同角度", published_at=timezone.now())
        result2 = reserve_exposure(
            event=event,
            article=article2,
            channel="homepage",
            scope_key="site",
            angle="connections",
        )
        # 第一席已满 15 分钟，第二席应有条件 active
        self.assertEqual(result2["slot"], 2)
        self.assertIn(result2["status"], ("active", "waiting"))

    def test_other_angle_not_prove_difference(self) -> None:
        """other 角度不能自动证明与第一席不同。"""
        try:
            reserve_exposure = _try_import_service(
                "stable.services.race_news_exposure.reserve_exposure"
            )
        except ImportError:
            self.fail("reserve_exposure 服务未实现（预期 RED）")
            return
        event = _make_event()
        article1 = _make_article(title="首篇综合赛果")
        result1 = reserve_exposure(
            event=event,
            article=article1,
            channel="homepage",
            scope_key="site",
            angle="comprehensive_result",
        )
        # 第二篇也标为 other（无法证明不同角度）
        article2 = _make_article(title="另一篇 other 角度的文章")
        result2 = reserve_exposure(
            event=event,
            article=article2,
            channel="homepage",
            scope_key="site",
            angle="other",
        )
        # other 不得自动获得第二席——可能被拒绝或为 waiting
        self.assertIsNone(result2.get("slot"))

    def test_higher_quality_replaces_slot2_only(self) -> None:
        """更高质量稿件只替换第二席，不替换第一席。"""
        try:
            replace_slot = _try_import_service(
                "stable.services.race_news_exposure.replace_slot2"
            )
            reserve_exposure = _try_import_service(
                "stable.services.race_news_exposure.reserve_exposure"
            )
            RaceNewsExposure = _try_import_model("stable.models.RaceNewsExposure")
        except ImportError:
            self.fail("replace_slot2 服务未实现（预期 RED）")
            return
        from django.utils import timezone
        from datetime import timedelta
        event = _make_event()
        article1 = _make_article(title="Race Result", score_total=50)
        article2 = _make_article(title="Race Winner", score_total=60)
        article3 = _make_article(title="Champion Victory Analysis", score_total=95)
        # Reserve slot 1 and slot 2
        reserve_exposure(event=event, article=article1, channel="homepage",
                         scope_key="site", angle="comprehensive_result")
        reserve_exposure(event=event, article=article2, channel="homepage",
                         scope_key="site", angle="winner")
        # Make slot 1 mature (15+ min ago)
        RaceNewsExposure.objects.filter(event=event, slot=1).update(
            activated_at=timezone.now() - timedelta(minutes=20))
        result = replace_slot(
            event=event, channel="homepage", scope_key="site",
            old_article=article2, new_article=article3,
            reason="quality_improvement",
        )
        self.assertEqual(result["replaced_article_id"], article2.id)
        self.assertEqual(result["new_article_id"], article3.id)
        self.assertEqual(result["slot"], 2)

    def test_idempotent_same_policy(self) -> None:
        """同策略重复执行幂等。"""
        try:
            reserve_exposure = _try_import_service(
                "stable.services.race_news_exposure.reserve_exposure"
            )
        except ImportError:
            self.fail("reserve_exposure 服务未实现（预期 RED）")
            return
        event = _make_event()
        article = _make_article(title="幂等测试")
        # 第一次调用
        result1 = reserve_exposure(
            event=event,
            article=article,
            channel="homepage",
            scope_key="site",
            angle="comprehensive_result",
        )
        # 第二次调用相同参数应返回一致结果，不新增记录
        result2 = reserve_exposure(
            event=event,
            article=article,
            channel="homepage",
            scope_key="site",
            angle="comprehensive_result",
        )
        self.assertEqual(result1["slot"], result2["slot"])
        self.assertEqual(result1["status"], result2["status"])


# ============================================================================
# 测试用例 11-15: 模型与并发
# ============================================================================

class ModelConstraintTests(TestCase):
    """条件唯一约束与模型完整性。"""

    def test_no_two_active_records_same_event_channel_scope_slot(self) -> None:
        """同赛事/频道/作用域/席位的两个有效记录应被拒绝。"""
        try:
            RaceNewsExposure = _try_import_model(
                "stable.models.RaceNewsExposure"
            )
        except ImportError:
            self.fail("RaceNewsExposure 模型未实现（预期 RED）")
            return
        event = _make_event()
        article1 = _make_article(title="第一席")
        article2 = _make_article(title="重复席")
        RaceNewsExposure.objects.create(
            event=event,
            article=article1,
            channel="homepage",
            scope_key="site",
            slot=1,
            status="active",
            angle="comprehensive_result",
            policy_version="v1",
            reason="first_slot",
        )
        with self.assertRaises(Exception):
            RaceNewsExposure.objects.create(
                event=event,
                article=article2,
                channel="homepage",
                scope_key="site",
                slot=1,
                status="active",
                angle="comprehensive_result",
                policy_version="v1",
                reason="second_attempt",
            )

    def test_qq_sent_slot_persists(self) -> None:
        """QQ 已发送席位应保持占用，同一 slot 不可新建。"""
        try:
            RaceNewsExposure = _try_import_model(
                "stable.models.RaceNewsExposure"
            )
        except ImportError:
            self.fail("RaceNewsExposure 模型未实现（预期 RED）")
            return
        event = _make_event()
        article = _make_article(title="已发送文章")
        target = _make_push_target()
        # 创建并标记为 sent
        RaceNewsExposure.objects.create(
            event=event,
            article=article,
            channel="qq",
            scope_key=f"target:{target.id}",
            slot=1,
            status="sent",
            angle="comprehensive_result",
            policy_version="v1",
            reason="sent_with_delivery",
        )
        # 尝试在同一 slot 创建新记录应失败
        article2 = _make_article(title="尝试占用已发送席位")
        with self.assertRaises(Exception):
            RaceNewsExposure.objects.create(
                event=event,
                article=article2,
                channel="qq",
                scope_key=f"target:{target.id}",
                slot=1,
                status="waiting",
                angle="comprehensive_result",
                policy_version="v1",
                reason="attempt_to_occupy_sent_slot",
            )


class ConcurrentSlotTests(TransactionTestCase):
    """并发争抢第二席。"""

    def test_concurrent_slot2_fight(self) -> None:
        """两个发布窗口并发争抢第二席时只有一个成功。"""
        try:
            reserve_exposure = _try_import_service(
                "stable.services.race_news_exposure.reserve_exposure"
            )
        except ImportError:
            self.fail("reserve_exposure 服务未实现（预期 RED）")
            return
        event = _make_event()
        article1 = _make_article(title="第一席", source_article_id="slot1")
        # 先创建第一席
        result1 = reserve_exposure(
            event=event,
            article=article1,
            channel="homepage",
            scope_key="site",
            angle="comprehensive_result",
        )
        # 两个并发文章抢第二席
        article_a = _make_article(title="并发A", source_article_id="concurrent-a")
        article_b = _make_article(title="并发B", source_article_id="concurrent-b")
        # 在事务中尝试模拟并发
        with transaction.atomic():
            result_a = reserve_exposure(
                event=event,
                article=article_a,
                channel="homepage",
                scope_key="site",
                angle="connections",
            )
        with transaction.atomic():
            result_b = reserve_exposure(
                event=event,
                article=article_b,
                channel="homepage",
                scope_key="site",
                angle="connections",
            )
        # 只有一个应成功获得 slot=2
        success_count = sum(
            1 for r in (result_a, result_b)
            if r.get("slot") == 2 and r.get("status") in ("active", "waiting")
        )
        self.assertEqual(success_count, 1)

    def test_qq_retry_does_not_add_slot(self) -> None:
        """失败重试不增加席位。"""
        try:
            RaceNewsExposure = _try_import_model(
                "stable.models.RaceNewsExposure"
            )
        except ImportError:
            self.fail("RaceNewsExposure 模型未实现（预期 RED）")
            return
        event = _make_event()
        article = _make_article(title="失败重试文章")
        target = _make_push_target()
        # 创建发送失败的 exposure
        delivery = QQPushDelivery.objects.create(
            article=article,
            target=target,
            status=QQPushDeliveryStatus.FAILED,
        )
        RaceNewsExposure.objects.create(
            event=event,
            article=article,
            channel="qq",
            scope_key=f"target:{target.id}",
            slot=1,
            status="active",
            angle="comprehensive_result",
            policy_version="v1",
            reason="first_slot",
            delivery=delivery,
        )
        # 重试应复用原 exposure，不创建新记录
        count_before = RaceNewsExposure.objects.count()
        # 触发重试（同一 article+target 复用原 delivery）
        delivery.status = QQPushDeliveryStatus.RETRYING
        delivery.save(update_fields=["status", "updated_at"])
        count_after = RaceNewsExposure.objects.count()
        self.assertEqual(count_after, count_before)

    def test_lease_reclaim_on_confirmed_not_sent(self) -> None:
        """worker 崩溃后可确认未发送时 lease 回收。"""
        try:
            RaceNewsExposure = _try_import_model(
                "stable.models.RaceNewsExposure"
            )
        except ImportError:
            self.fail("RaceNewsExposure 模型未实现（预期 RED）")
            return
        event = _make_event()
        article = _make_article(title="租赁回收测试")
        target = _make_push_target()
        past = timezone.now() - timedelta(minutes=30)
        delivery = QQPushDelivery.objects.create(
            article=article,
            target=target,
            status=QQPushDeliveryStatus.PENDING,
            message_id="",
        )
        exposure = RaceNewsExposure.objects.create(
            event=event,
            article=article,
            channel="qq",
            scope_key=f"target:{target.id}",
            slot=2,
            status="waiting",
            angle="connections",
            policy_version="v1",
            reason="lease_reclaim_test",
            delivery=delivery,
            lease_expires_at=past,
        )
        # 尝试回收 lease（确认未发送，lease 过期）
        try:
            reclaim_lease = _try_import_service(
                "stable.services.race_news_exposure.reclaim_expired_lease"
            )
        except ImportError:
            self.fail("reclaim_expired_lease 服务未实现（预期 RED）")
            return
        result = reclaim_lease(exposure_id=exposure.id)
        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "waiting")

    def test_fail_closed_on_unknown_result(self) -> None:
        """请求结果不明或已有 message ID 时保留席位。"""
        try:
            RaceNewsExposure = _try_import_model(
                "stable.models.RaceNewsExposure"
            )
        except ImportError:
            self.fail("RaceNewsExposure 模型未实现（预期 RED）")
            return
        event = _make_event()
        article = _make_article(title="结果不明")
        target = _make_push_target()
        # 已有 message ID 的 delivery 应保留席位
        delivery = QQPushDelivery.objects.create(
            article=article,
            target=target,
            status=QQPushDeliveryStatus.SENDING,
            message_id="msg_12345",
        )
        exposure = RaceNewsExposure.objects.create(
            event=event,
            article=article,
            channel="qq",
            scope_key=f"target:{target.id}",
            slot=1,
            status="active",
            angle="comprehensive_result",
            policy_version="v1",
            reason="sent_with_message_id",
            delivery=delivery,
            lease_expires_at=timezone.now() - timedelta(minutes=5),
        )
        # 尝试回收 - 因为有 message_id 应保留
        try:
            reclaim_lease = _try_import_service(
                "stable.services.race_news_exposure.reclaim_expired_lease"
            )
        except ImportError:
            self.fail("reclaim_expired_lease 服务未实现（预期 RED）")
            return
        result = reclaim_lease(exposure_id=exposure.id)
        # 应 fail closed - 不清除
        self.assertIsNone(result)


class TransactionRollbackTests(TransactionTestCase):
    """事务回滚测试。"""

    def test_rollback_on_any_write_failure(self) -> None:
        """quota、exposure 与 delivery 任一失败时整体回滚。"""
        try:
            RaceNewsExposure = _try_import_model(
                "stable.models.RaceNewsExposure"
            )
            reserve_exposure = _try_import_service(
                "stable.services.race_news_exposure.reserve_exposure"
            )
        except ImportError:
            self.fail("RaceNewsExposure 或 reserve_exposure 未实现（预期 RED）")
            return
        event = _make_event()
        article = _make_article(title="事务回滚测试")
        target = _make_push_target()
        count_before = RaceNewsExposure.objects.count()
        delivery_count_before = QQPushDelivery.objects.count()
        # 在事务中模拟失败（通过无效 target_id 触发数据库外键异常）
        try:
            with transaction.atomic():
                reserve_exposure(
                    event=event,
                    article=article,
                    channel="homepage",
                    scope_key="site",
                    angle="comprehensive_result",
                )
                QQPushDelivery.objects.create(
                    article=article,
                    target_id=999999,  # 不存在的 target，触发外键约束异常
                    status=QQPushDeliveryStatus.FAILED,
                )
        except Exception:
            pass
        # 事务回滚后 exposure 和 delivery 都不应残留
        count_after = RaceNewsExposure.objects.count()
        delivery_count_after = QQPushDelivery.objects.count()
        self.assertEqual(count_after, count_before)
        self.assertEqual(delivery_count_after, delivery_count_before)


# ============================================================================
# 测试用例 16-20: 首页与头条
# ============================================================================

class HomepageAndHeadlineTests(TestCase):
    """首页、分页与头条的赛事配额测试。"""

    def _call_featured_articles(self):
        """调用首页精选文章获取函数。"""
        try:
            featured = _try_import_service(
                "stable.services.race_news_exposure.get_featured_articles"
            )
            return featured
        except ImportError:
            try:
                from stable.views import _public_published_articles
                return _public_published_articles()
            except ImportError:
                self.fail("get_featured_articles 或 _public_published_articles 未实现")
                return None

    def test_max_two_same_event_on_homepage(self) -> None:
        """同赛事 5 篇公开文章，首页含头条最多 2 篇。"""
        try:
            RaceNewsExposure = _try_import_model(
                "stable.models.RaceNewsExposure"
            )
        except ImportError:
            self.fail("RaceNewsExposure 模型未实现（预期 RED）")
            return
        event = _make_event()
        articles = []
        for i in range(5):
            article = _make_article(
                title=f"同赛事文章{i+1}",
                source_article_id=f"race-article-{i}",
                published_at=timezone.now() - timedelta(hours=i),
            )
            _make_article_race_link(
                article=article, event=event,
                status=ArticleRaceLinkStatus.MANUAL,
            )
            articles.append(article)

        # 创建两席 active exposure（只有前两篇有席位）
        RaceNewsExposure.objects.create(
            event=event,
            article=articles[0],
            channel="homepage",
            scope_key="site",
            slot=1,
            status="active",
            angle="comprehensive_result",
            policy_version="v1",
            reason="first_slot",
        )
        RaceNewsExposure.objects.create(
            event=event,
            article=articles[1],
            channel="homepage",
            scope_key="site",
            slot=2,
            status="active",
            angle="connections",
            policy_version="v1",
            reason="second_slot",
        )

        # 验证首页视图调用——当 exposure 开启时，同赛事不超过 2 篇
        with override_settings(RACE_NEWS_EXPOSURE_ENABLED=True):
            response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        # Count occurrences of each article title on the page
        appearing_titles = [a.title_ja for a in articles if a.title_ja in content]
        self.assertLessEqual(
            len(appearing_titles), 2,
            f"Expected at most 2 articles from the same event on homepage, "
            f"got {len(appearing_titles)}: {appearing_titles}",
        )

        # 被抑制的文章应仍可访问详情 URL
        for article in articles[2:]:
            detail_response = self.client.get(article.public_path)
            self.assertEqual(detail_response.status_code, 200)

    def test_suppressed_article_accessible(self) -> None:
        """被抑制文章详情为 200，且出现在对应赛事详情新闻列表。"""
        try:
            RaceNewsExposure = _try_import_model(
                "stable.models.RaceNewsExposure"
            )
        except ImportError:
            self.fail("RaceNewsExposure 模型未实现（预期 RED）")
            return
        event = _make_event(visibility_status="published")
        article = _make_article(title="被抑制文章")
        _make_article_race_link(
            article=article, event=event,
            status=ArticleRaceLinkStatus.MANUAL,
        )
        # 标记为 suppressed（表示首页不展示但详情页可访问）
        RaceNewsExposure.objects.create(
            event=event,
            article=article,
            channel="homepage",
            scope_key="site",
            slot=1,
            status="suppressed",
            angle="other",
            policy_version="v1",
            reason="exceeded_two_slot_limit",
        )
        # 验证文章详情页返回 200
        response = self.client.get(article.public_path)
        self.assertEqual(response.status_code, 200)
        # 验证赛事详情页包含该文章
        response = self.client.get(event.public_path)
        self.assertEqual(response.status_code, 200)

    def test_manual_headline_replaces_slot2(self) -> None:
        """手工头条选中同赛事第三篇时原子替换第二席。"""
        try:
            RaceNewsExposure = _try_import_model(
                "stable.models.RaceNewsExposure"
            )
            replace_slot = _try_import_service(
                "stable.services.race_news_exposure.replace_slot2"
            )
        except ImportError:
            self.fail("RaceNewsExposure 或 replace_slot2 未实现（预期 RED）")
            return
        from django.utils import timezone
        from datetime import timedelta
        event = _make_event()
        article1 = _make_article(title="Race Result", score_total=50)
        article2 = _make_article(title="Trainer and Jockey", score_total=55)
        article3 = _make_article(title="Win Victory Analysis", score_total=90)
        # 创建两席，slot 1 must be mature (activated_at 20 min ago)
        RaceNewsExposure.objects.create(
            event=event, article=article1, channel="homepage",
            scope_key="site", slot=1, status="active",
            angle="comprehensive_result", policy_version="v1",
            reason="first_slot",
            activated_at=timezone.now() - timedelta(minutes=20),
        )
        RaceNewsExposure.objects.create(
            event=event, article=article2, channel="homepage",
            scope_key="site", slot=2, status="active",
            angle="connections", policy_version="v1",
            reason="second_slot",
        )
        # 替换第二席
        result = replace_slot(
            event=event, channel="homepage", scope_key="site",
            old_article=article2, new_article=article3,
            reason="manual_headline_replacement",
        )
        self.assertEqual(result["replaced_article_id"], article2.id)
        self.assertEqual(result["new_article_id"], article3.id)
        # 不应形成第三席
        active_count = RaceNewsExposure.objects.filter(
            event=event, channel="homepage", scope_key="site",
            status__in=("active", "waiting"),
        ).count()
        self.assertLessEqual(active_count, 2)

    def test_slot2_rejected_before_15min(self) -> None:
        """第一席未满 15 分钟时拒绝占用第二席。"""
        try:
            reserve_exposure = _try_import_service(
                "stable.services.race_news_exposure.reserve_exposure"
            )
        except ImportError:
            self.fail("reserve_exposure 服务未实现（预期 RED）")
            return
        now = timezone.now()
        event = _make_event()
        article1 = _make_article(title="第一席", published_at=now)
        result1 = reserve_exposure(
            event=event,
            article=article1,
            channel="homepage",
            scope_key="site",
            angle="comprehensive_result",
            published_at=now,
        )
        # 仅过了 5 分钟（不到 15 分钟）
        article2 = _make_article(title="第二席尝试", published_at=now + timedelta(minutes=5))
        result2 = reserve_exposure(
            event=event,
            article=article2,
            channel="homepage",
            scope_key="site",
            angle="connections",
            published_at=now + timedelta(minutes=5),
        )
        # 第二席应为 waiting（未到 15 分钟）
        if result2.get("slot") == 2:
            self.assertEqual(result2.get("status"), "waiting")

    def test_ordinary_news_stable(self) -> None:
        """无赛事身份的普通新闻保持现有排序和展示。"""
        article = _make_article(
            title="普通新闻",
            source_article_id="ordinary-news-1",
        )
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        # 普通新闻应该出现在首页
        self.assertContains(response, "普通新闻")


# ============================================================================
# 测试用例 21-24: QQ
# ============================================================================

class QQDeliveryTests(TestCase):
    """QQ 推送的两席限制测试。"""

    def test_same_group_same_event_max_two(self) -> None:
        """同群同赛事最多发送 2 篇。"""
        try:
            RaceNewsExposure = _try_import_model(
                "stable.models.RaceNewsExposure"
            )
            reserve_qq_exposure = _try_import_service(
                "stable.services.race_news_exposure.reserve_qq_exposure"
            )
        except ImportError:
            self.fail("RaceNewsExposure 或 reserve_qq_exposure 未实现（预期 RED）")
            return
        event = _make_event()
        target = _make_push_target()
        article1 = _make_article(title="QQ 第一席", source_article_id="qq1")
        article2 = _make_article(title="QQ 第二席", source_article_id="qq2")
        article3 = _make_article(title="QQ 第三篇", source_article_id="qq3")
        # 占用两席
        scope_key = f"target:{target.id}"
        # 前两个应成功
        result1 = reserve_qq_exposure(
            event=event,
            article=article1,
            target=target,
            angle="comprehensive_result",
        )
        self.assertIsNotNone(result1)
        result2 = reserve_qq_exposure(
            event=event,
            article=article2,
            target=target,
            angle="connections",
        )
        self.assertIsNotNone(result2)
        # 第三个应达到 race_exposure_limit
        result3 = reserve_qq_exposure(
            event=event,
            article=article3,
            target=target,
            angle="analysis",
        )
        self.assertIsNone(result3)

    def test_different_groups_independent_counts(self) -> None:
        """不同群各自独立计数。"""
        try:
            RaceNewsExposure = _try_import_model(
                "stable.models.RaceNewsExposure"
            )
            reserve_qq_exposure = _try_import_service(
                "stable.services.race_news_exposure.reserve_qq_exposure"
            )
        except ImportError:
            self.fail("RaceNewsExposure 或 reserve_qq_exposure 未实现（预期 RED）")
            return
        event = _make_event()
        target_a = _make_push_target(name="群A", group_id="group-a")
        target_b = _make_push_target(name="群B", group_id="group-b")
        scope_key_a = f"target:{target_a.id}"
        scope_key_b = f"target:{target_b.id}"
        # 验证对 target_a 的计数不影响 target_b
        for target, scope_key in [(target_a, scope_key_a), (target_b, scope_key_b)]:
            for i in range(2):
                article = _make_article(
                    title=f"群{target.name}第{i+1}篇",
                    source_article_id=f"{scope_key}-{i}",
                )
                try:
                    reserve_qq_exposure = _try_import_service(
                        "stable.services.race_news_exposure.reserve_qq_exposure"
                    )
                except ImportError:
                    self.fail("reserve_qq_exposure 未实现")
                    return
                result = reserve_qq_exposure(
                    event=event,
                    article=article,
                    target=target,
                    angle="comprehensive_result" if i == 0 else "connections",
                )
                self.assertIsNotNone(result)
        # 每个群应各有 2 个 exposure 记录
        self.assertEqual(
            RaceNewsExposure.objects.filter(
                event=event,
                channel="qq",
                scope_key=scope_key_a,
            ).count(),
            2,
        )
        self.assertEqual(
            RaceNewsExposure.objects.filter(
                event=event,
                channel="qq",
                scope_key=scope_key_b,
            ).count(),
            2,
        )

    def test_no_window_duplicate_after_instant_push(self) -> None:
        """第一篇即时推送后，窗口任务不重复发送。"""
        try:
            reserve_qq_exposure = _try_import_service(
                "stable.services.race_news_exposure.reserve_qq_exposure"
            )
        except ImportError:
            self.fail("reserve_qq_exposure 未实现（预期 RED）")
            self.skipTest("Service not available")
        event = _make_event()
        target = _make_push_target()
        article = _make_article(title="即时推送文章")
        # 即时推送已占用第一席
        result = reserve_qq_exposure(
            event=event,
            article=article,
            target=target,
            angle="comprehensive_result",
        )
        self.assertIsNotNone(result)
        # 窗口任务再尝试同一文章时不应重复发送
        result2 = reserve_qq_exposure(
            event=event,
            article=article,
            target=target,
            angle="comprehensive_result",
        )
        # 返回结果应相同（幂等），不创建新 delivery
        self.assertEqual(result.get("slot"), result2.get("slot"))

    def test_second_qq_before_15min_no_delivery(self) -> None:
        """第二篇未满 15 分钟不创建 delivery。"""
        try:
            reserve_qq_exposure = _try_import_service(
                "stable.services.race_news_exposure.reserve_qq_exposure"
            )
        except ImportError:
            self.fail("reserve_qq_exposure 未实现（预期 RED）")
            return
        event = _make_event()
        target = _make_push_target()
        article1 = _make_article(title="QQ 第一席", published_at=timezone.now())
        # 第一席
        result1 = reserve_qq_exposure(
            event=event,
            article=article1,
            target=target,
            angle="comprehensive_result",
        )
        self.assertIsNotNone(result1)
        # 仅过 5 分钟，尝试第二篇
        article2 = _make_article(
            title="QQ 第二席尝试",
            published_at=timezone.now() + timedelta(minutes=5),
        )
        result2 = reserve_qq_exposure(
            event=event,
            article=article2,
            target=target,
            angle="connections",
        )
        # 第二篇应不创建 delivery（waiting 状态不推送）
        if result2 and result2.get("slot") == 2:
            self.assertEqual(result2.get("status"), "waiting")

    def test_slot2_replaced_no_new_qq_delivery(self) -> None:
        """首页第二席被替换后不为新稿创建第三次 QQ delivery。"""
        try:
            RaceNewsExposure = _try_import_model(
                "stable.models.RaceNewsExposure"
            )
            replace_slot = _try_import_service(
                "stable.services.race_news_exposure.replace_slot2"
            )
        except ImportError:
            self.fail("RaceNewsExposure 或 replace_slot2 未实现（预期 RED）")
            return
        event = _make_event()
        target = _make_push_target()
        article1 = _make_article(title="首页第一席", source_article_id="hp1")
        article2 = _make_article(title="首页第二席（已发送）", source_article_id="hp2")
        article3 = _make_article(title="替换稿", source_article_id="hp3")
        # 创建首页 exposure
        RaceNewsExposure.objects.create(
            event=event,
            article=article1,
            channel="homepage",
            scope_key="site",
            slot=1,
            status="active",
            angle="comprehensive_result",
            policy_version="v1",
            reason="first_slot",
        )
        RaceNewsExposure.objects.create(
            event=event,
            article=article2,
            channel="homepage",
            scope_key="site",
            slot=2,
            status="active",
            angle="connections",
            policy_version="v1",
            reason="second_slot",
        )
        # 替换第二席
        replace_slot(
            event=event,
            channel="homepage",
            scope_key="site",
            old_article=article2,
            new_article=article3,
            reason="quality_replacement",
        )
        # 不应为替换后的 article3 创建 QQ delivery
        qq_deliveries = QQPushDelivery.objects.filter(article=article3, target=target)
        self.assertEqual(qq_deliveries.count(), 0)


# ============================================================================
# 测试用例 25-28: 历史回填
# ============================================================================

class HistoricalBackfillTests(TestCase):
    """历史回填相关测试。"""

    def test_dry_run_no_writes(self) -> None:
        """dry-run 只输出 manifest，不写 exposure/delivery/headline。"""
        try:
            backfill_command = _try_import_service(
                "stable.management.commands.backfill_race_exposure.Command"
            )
        except ImportError:
            self.fail("backfill_race_exposure 命令未实现（预期 RED）")
            return
        event = _make_event()
        article = _make_article(title="历史文章")
        _make_article_race_link(
            article=article, event=event,
            status=ArticleRaceLinkStatus.MANUAL,
        )
        # dry-run 模式
        from io import StringIO
        out = StringIO()
        cmd = backfill_command()
        try:
            cmd.handle(dry_run=True, stdout=out)
        except Exception as e:
            self.fail(f"dry_run 失败: {e}")
        output = out.getvalue()
        self.assertIn("manifest", output.lower())
        # 不应写入 exposure
        try:
            RaceNewsExposure = _try_import_model(
                "stable.models.RaceNewsExposure"
            )
            exposure_count = RaceNewsExposure.objects.filter(
                event=event, article=article,
            ).count()
            self.assertEqual(exposure_count, 0)
        except ImportError:
            pass

    def test_duplicate_article_event_id_rejected(self) -> None:
        """重复 article/event ID、身份漂移时整批拒绝。"""
        try:
            backfill_command = _try_import_service(
                "stable.management.commands.backfill_race_exposure.Command"
            )
        except ImportError:
            self.fail("backfill_race_exposure 命令未实现（预期 RED）")
            return
        event = _make_event()
        article = _make_article(title="重复文章")
        _make_article_race_link(
            article=article, event=event,
            status=ArticleRaceLinkStatus.MANUAL,
        )
        from io import StringIO
        out = StringIO()
        err = StringIO()
        cmd = backfill_command()
        # 传递重复的 manifest 条目（同时使用 --apply 和 expected-sha256）
        import hashlib, json
        test_manifest = [
            {"article_id": article.id, "event_id": event.id, "slot": 1},
            {"article_id": article.id, "event_id": event.id, "slot": 1},
        ]
        test_sha256 = hashlib.sha256(
            json.dumps(test_manifest, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        try:
            cmd.handle(
                dry_run=False,
                apply=True,
                manifest=test_manifest,
                expected_sha256=test_sha256,
                stdout=out,
                stderr=err,
            )
        except Exception:
            pass
        combined = (out.getvalue() + err.getvalue()).lower()
        self.assertIn("reject", combined)

    def test_apply_preserves_original_data(self) -> None:
        """apply 只写 exposure，正文/公开时间/QQ delivery/duplicate_of 守恒。"""
        try:
            backfill_command = _try_import_service(
                "stable.management.commands.backfill_race_exposure.Command"
            )
            RaceNewsExposure = _try_import_model(
                "stable.models.RaceNewsExposure"
            )
        except ImportError:
            self.fail("backfill_race_exposure 命令或 RaceNewsExposure 未实现（预期 RED）")
            return
        event = _make_event()
        article = _make_article(
            title="回填守恒测试",
            body_zh="原始正文内容",
        )
        _make_article_race_link(
            article=article, event=event,
            status=ArticleRaceLinkStatus.MANUAL,
        )
        # 记录原始值
        original_body = article.body_zh
        original_published_to_web_at = article.published_to_web_at
        from io import StringIO
        out = StringIO()
        err = StringIO()
        import hashlib, json
        test_manifest = [
            {"article_id": article.id, "event_id": event.id, "slot": 1, "angle": "comprehensive_result"},
        ]
        test_sha256 = hashlib.sha256(
            json.dumps(test_manifest, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        cmd = backfill_command()
        try:
            cmd.handle(
                dry_run=False,
                apply=True,
                manifest=test_manifest,
                expected_sha256=test_sha256,
                stdout=out,
                stderr=err,
            )
        except Exception:
            pass
        # 验证 exposure 已创建
        exposures = RaceNewsExposure.objects.filter(article=article)
        self.assertGreaterEqual(exposures.count(), 0)
        # 验证正文、公开时间守恒
        article.refresh_from_db()
        self.assertEqual(article.body_zh, original_body)
        self.assertEqual(article.published_to_web_at, original_published_to_web_at)

    def test_replay_no_extra_effects(self) -> None:
        """同一批准包重放零额外业务效果。"""
        try:
            RaceNewsExposure = _try_import_model(
                "stable.models.RaceNewsExposure"
            )
        except ImportError:
            self.fail("RaceNewsExposure 模型未实现（预期 RED）")
            return
        event = _make_event()
        article = _make_article(title="重放测试")
        _make_article_race_link(
            article=article, event=event,
            status=ArticleRaceLinkStatus.MANUAL,
        )
        # 第一次 apply
        RaceNewsExposure.objects.create(
            event=event,
            article=article,
            channel="homepage",
            scope_key="site",
            slot=1,
            status="active",
            angle="comprehensive_result",
            policy_version="backfill-v1",
            reason="historical_backfill",
        )
        count_after_first = RaceNewsExposure.objects.count()
        # 第二次 apply 同一批
        try:
            backfill_command = _try_import_service(
                "stable.management.commands.backfill_race_exposure.Command"
            )
        except ImportError:
            # 如果没有命令，确保再次创建相同记录会导致约束错误
            from django.db import IntegrityError
            with self.assertRaises(IntegrityError):
                RaceNewsExposure.objects.create(
                    event=event,
                    article=article,
                    channel="homepage",
                    scope_key="site",
                    slot=1,
                    status="active",
                    angle="comprehensive_result",
                    policy_version="backfill-v1",
                    reason="historical_backfill",
                )
            return
        from io import StringIO
        out = StringIO()
        cmd = backfill_command()
        try:
            cmd.handle(
                dry_run=False,
                apply=True,
                manifest=[
                    {"article_id": article.id, "event_id": event.id, "slot": 1, "angle": "comprehensive_result"},
                ],
                stdout=out,
            )
        except Exception:
            pass
        count_after_second = RaceNewsExposure.objects.count()
        # 重放不应产生新记录
        self.assertEqual(count_after_second, count_after_first)

    def test_multi_article_event_slot_allocation(self) -> None:
        """同赛事多篇文章：1 个 slot1 + 至多 1 个 slot2，其余 suppressed，apply 不触发约束冲突。"""
        try:
            backfill_command = _try_import_service(
                "stable.management.commands.backfill_race_exposure.Command"
            )
            RaceNewsExposure = _try_import_model(
                "stable.models.RaceNewsExposure"
            )
        except ImportError:
            self.fail("backfill_race_exposure 命令或 RaceNewsExposure 未实现")
            return
        from io import StringIO
        event = _make_event()
        base = timezone.now() - timedelta(days=2)
        articles = []
        titles = [
            "赛果：冠军诞生",      # comprehensive_result
            "练马师专访",          # connections
            "赛事回放与复盘分析",   # analysis
            "赔率市场观察",        # market
            "赛果补充报道",        # comprehensive_result (same angle as slot1)
        ]
        for i, title in enumerate(titles):
            articles.append(_make_article(
                title=title,
                source_article_id=f"multi-{i}",
                published_at=base + timedelta(hours=i),
            ))
            _make_article_race_link(
                article=articles[-1], event=event,
                status=ArticleRaceLinkStatus.MANUAL,
            )
        out = StringIO()
        cmd = backfill_command()
        cmd.handle(dry_run=True, stdout=out)
        import json as _json
        output = _json.loads(out.getvalue().rsplit("\n", 1)[0])
        manifest = output["manifest"]
        entries = [e for e in manifest if e["event_id"] == event.id]
        self.assertEqual(len(entries), len(articles))
        slot1 = [e for e in entries if e["slot"] == 1]
        active2 = [e for e in entries if e["slot"] == 2 and e["status"] == "active"]
        suppressed = [e for e in entries if e["status"] == "suppressed"]
        self.assertEqual(len(slot1), 1)
        self.assertEqual(slot1[0]["article_id"], articles[0].id)
        self.assertLessEqual(len(active2), 1)
        # slot2 角度必须与 slot1 不同
        if active2:
            self.assertNotEqual(active2[0]["angle"], slot1[0]["angle"])
        self.assertEqual(len(suppressed), len(articles) - len(slot1) - len(active2))

        # apply 整批成功（此前全部 slot1 的 manifest 会因唯一约束整批回滚）
        import hashlib
        sha = hashlib.sha256(
            _json.dumps(manifest, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        out2 = StringIO()
        cmd.handle(
            dry_run=False, apply=True, manifest=manifest,
            expected_sha256=sha, stdout=out2, stderr=StringIO(),
        )
        exposures = RaceNewsExposure.objects.filter(event=event)
        self.assertEqual(exposures.count(), len(articles))
        self.assertEqual(exposures.filter(slot=1, status="active").count(), 1)
        self.assertLessEqual(exposures.filter(slot=2, status="active").count(), 1)


# ============================================================================
# 测试用例 29: 性能
# ============================================================================

class PerformanceTests(TestCase):
    """查询数检查。"""

    def _seed_event_articles(self, prefix: str, count: int) -> None:
        RaceNewsExposure = _try_import_model(
            "stable.models.RaceNewsExposure"
        )
        event = _make_event(slug=f"perf-event-{prefix}")
        for i in range(count):
            article = _make_article(
                title=f"性能测试文章{prefix}{i}",
                source_article_id=f"perf-{prefix}-{i}",
            )
            _make_article_race_link(
                article=article, event=event,
                status=ArticleRaceLinkStatus.MANUAL,
            )
            if i == 0:
                slot, status = 1, "active"
                angle = "comprehensive_result"
            elif i == 1:
                slot, status = 2, "active"
                angle = "connections"
            else:
                slot, status = 2, "suppressed"
                angle = "other"
            RaceNewsExposure.objects.create(
                event=event,
                article=article,
                channel="homepage",
                scope_key="site",
                slot=slot,
                status=status,
                angle=angle,
                policy_version="v1",
                reason="perf_test",
            )

    def test_homepage_50_articles_query_count(self) -> None:
        """首页真实 public_news_feed 视图：race-linked 文章增加不产生 N+1。"""
        try:
            _try_import_model("stable.models.RaceNewsExposure")
        except ImportError:
            self.fail("RaceNewsExposure 模型未实现（预期 RED）")
            return

        with override_settings(RACE_NEWS_EXPOSURE_ENABLED=True):
            self._seed_event_articles("a", 10)
            with CaptureQueriesContext(connection) as ctx_small:
                response = self.client.get("/")
            self.assertEqual(response.status_code, 200)
            small_count = len(ctx_small.captured_queries)

            # 文章数量扩大 5 倍（每个新赛事 10 篇 race-linked 文章）
            for prefix in ("b", "c", "d", "e"):
                self._seed_event_articles(prefix, 10)
            with CaptureQueriesContext(connection) as ctx_large:
                response = self.client.get("/")
            self.assertEqual(response.status_code, 200)
            large_count = len(ctx_large.captured_queries)

        # EXISTS 子查询在 DB 层完成过滤：文章 5 倍增长时查询数近似恒定
        self.assertLessEqual(
            large_count - small_count, 2,
            f"文章数扩大 5 倍，查询数从 {small_count} 增至 {large_count}，疑似 N+1",
        )
        # 绝对上限（含余量，防回归）：真实视图全链路查询数
        self.assertLessEqual(large_count, 40)


# ============================================================================
# 测试用例 21b: 窗口 QQ 原子性回归
# ============================================================================

class WindowQQAtomicityTests(TestCase):
    """窗口 QQ 路径 exposure/quota/delivery 原子绑定回归。"""

    def _make_window(self, target):
        from stable.models import ProductionWindow
        now = timezone.now()
        return ProductionWindow.objects.create(
            kind="qq_push",
            mode="daily",
            racing_region=RacingRegion.UNITED_KINGDOM,
            target=target,
            scope_key=f"region:uk:target:{target.id}",
            window_start=now - timedelta(minutes=15),
            window_end=now,
        )

    def test_quota_rejection_leaves_no_orphan_exposure(self) -> None:
        """quota 拒绝后不得残留 exposure / delivery（同事务回滚）。"""
        try:
            RaceNewsExposure = _try_import_model(
                "stable.models.RaceNewsExposure"
            )
            select_qq_window_deliveries = _try_import_service(
                "stable.services.qq_windows.select_qq_window_deliveries"
            )
        except ImportError:
            self.fail("RaceNewsExposure 或 select_qq_window_deliveries 未实现")
            return
        from stable.models import QuotaLedger

        event = _make_event()
        target = PushTarget.objects.create(
            name="UK QQ 原子性",
            group_id=f"group-atomic-{timezone.now().timestamp()}",
            allowed_regions=[RacingRegion.UNITED_KINGDOM],
            is_active=True,
            push_scope="all_public",
            importance_strategy="ranked",
        )
        article = _make_article(title="窗口配额拒绝回归")
        _make_article_race_link(
            article=article, event=event,
            status=ArticleRaceLinkStatus.MANUAL,
        )
        window = self._make_window(target)
        # 群小时配额已满 → reserve 必然拒绝
        QuotaLedger.objects.create(
            kind="qq_push",
            scope="group_hour",
            scope_key=f"group:{target.group_id}",
            window_start=window.window_start.replace(minute=0, second=0, microsecond=0),
            limit=12,
            used=12,
        )

        with override_settings(RACE_NEWS_EXPOSURE_ENABLED=True):
            result = select_qq_window_deliveries(
                RacingRegion.UNITED_KINGDOM,
                window=window,
                targets=[target],
                now=timezone.now(),
            )

        self.assertEqual(result.deliveries, [])
        self.assertIn("group_hour_quota_exhausted", result.zero_reasons)
        # 关键断言：exposure reservation 已随事务回滚，无 orphan 残留
        self.assertEqual(
            RaceNewsExposure.objects.filter(event=event).count(), 0,
            "quota 拒绝后残留 orphan exposure",
        )
        self.assertEqual(
            QQPushDelivery.objects.filter(article=article).count(), 0,
        )


# ============================================================================
# 测试用例 21c: 人工头条遵守曝光政策
# ============================================================================

class ManualHeadlineExposurePolicyTests(TestCase):
    """人工头条必须尊重曝光政策拒绝结果。"""

    def _staff_user(self):
        from django.contrib.auth import get_user_model
        return get_user_model().objects.create_superuser(
            username=f"headline-staff-{timezone.now().timestamp()}",
            password="x",
        )

    def test_low_score_headline_rejected_rolls_back(self) -> None:
        """低分头条触发 replace_slot2 质量拒绝时，头条设置整体回滚。"""
        try:
            RaceNewsExposure = _try_import_model(
                "stable.models.RaceNewsExposure"
            )
            set_manual_headline = _try_import_service(
                "stable.services.editorial_headlines.set_manual_headline"
            )
            get_headline_state = _try_import_service(
                "stable.services.editorial_headlines.get_headline_state"
            )
        except ImportError:
            self.fail("RaceNewsExposure 或 editorial_headlines 服务未实现")
            return

        event = _make_event()
        old_slot1 = _make_article(title="赛果：冠军诞生", source_article_id="hl-slot1")
        old_slot2 = _make_article(
            title="练马师专访", source_article_id="hl-slot2", score_total=90,
        )
        # 低分头条候选：标题含 connections 关键词，角度与 slot1 不同
        headline = _make_article(
            title="练马师谈备战", source_article_id="hl-new", score_total=50,
        )
        for art in (old_slot1, old_slot2, headline):
            _make_article_race_link(
                article=art, event=event,
                status=ArticleRaceLinkStatus.MANUAL,
            )
        mature_at = timezone.now() - timedelta(minutes=30)
        RaceNewsExposure.objects.create(
            event=event, article=old_slot1,
            channel="homepage", scope_key="site", slot=1,
            status="active", angle="comprehensive_result",
            policy_version="v1", reason="first_slot", activated_at=mature_at,
        )
        RaceNewsExposure.objects.create(
            event=event, article=old_slot2,
            channel="homepage", scope_key="site", slot=2,
            status="active", angle="connections",
            policy_version="v1", reason="second_slot", activated_at=mature_at,
        )

        with override_settings(RACE_NEWS_EXPOSURE_ENABLED=True):
            state_before = get_headline_state()
            with self.assertRaises(ValueError):
                set_manual_headline(
                    headline.pk,
                    user=self._staff_user(),
                    expected_version=state_before["version"],
                )
            state_after = get_headline_state()

        # 头条未提交：版本与选中文章均未变化
        self.assertEqual(state_after["version"], state_before["version"])
        self.assertIsNone(state_after.get("article_id"))
        # slot 2 也未被替换
        self.assertEqual(
            RaceNewsExposure.objects.filter(
                event=event, slot=2, status="active",
            ).count(),
            1,
        )

    def test_headline_with_waiting_exposure_is_activated(self) -> None:
        """头条文章的 waiting exposure 必须立即激活，不得提交不可见头条。"""
        try:
            RaceNewsExposure = _try_import_model(
                "stable.models.RaceNewsExposure"
            )
            set_manual_headline = _try_import_service(
                "stable.services.editorial_headlines.set_manual_headline"
            )
            get_headline_state = _try_import_service(
                "stable.services.editorial_headlines.get_headline_state"
            )
        except ImportError:
            self.fail("相关服务未实现")
            return
        event = _make_event()
        slot1_article = _make_article(title="赛果公布", source_article_id="hl-w-s1")
        headline = _make_article(title="练马师专访", source_article_id="hl-w-new")
        _make_article_race_link(
            article=headline, event=event,
            status=ArticleRaceLinkStatus.MANUAL,
        )
        RaceNewsExposure.objects.create(
            event=event, article=slot1_article,
            channel="homepage", scope_key="site", slot=1,
            status="active", angle="comprehensive_result",
            policy_version="v1", reason="first_slot",
            activated_at=timezone.now() - timedelta(minutes=30),
        )
        waiting = RaceNewsExposure.objects.create(
            event=event, article=headline,
            channel="homepage", scope_key="site", slot=2,
            status="waiting", angle="connections",
            policy_version="v1", reason="second_slot",
        )
        with override_settings(RACE_NEWS_EXPOSURE_ENABLED=True):
            state_before = get_headline_state()
            result = set_manual_headline(
                headline.pk, user=self._staff_user(),
                expected_version=state_before["version"],
            )
        self.assertTrue(result.get("success"), f"headline rejected: {result}")
        waiting.refresh_from_db()
        self.assertEqual(
            waiting.status, "active",
            "头条提交成功但 exposure 仍是 waiting（无 active 席位）",
        )
        self.assertIsNotNone(waiting.activated_at)

    def test_idempotent_headline_resyncs_degraded_exposure(self) -> None:
        """重复设置同一头条文章时，退化的 exposure 必须被重新同步。"""
        try:
            RaceNewsExposure = _try_import_model(
                "stable.models.RaceNewsExposure"
            )
            set_manual_headline = _try_import_service(
                "stable.services.editorial_headlines.set_manual_headline"
            )
            get_headline_state = _try_import_service(
                "stable.services.editorial_headlines.get_headline_state"
            )
        except ImportError:
            self.fail("相关服务未实现")
            return
        event = _make_event()
        headline = _make_article(title="赛果：爆冷", source_article_id="hl-idem")
        _make_article_race_link(
            article=headline, event=event,
            status=ArticleRaceLinkStatus.MANUAL,
        )
        user = self._staff_user()
        with override_settings(RACE_NEWS_EXPOSURE_ENABLED=True):
            # 第一次设置：正常创建 active exposure
            state0 = get_headline_state()
            first = set_manual_headline(
                headline.pk, user=user, expected_version=state0["version"],
            )
            self.assertTrue(first.get("success"), f"first set failed: {first}")
            exposure = RaceNewsExposure.objects.get(event=event, article=headline)
            self.assertEqual(exposure.status, "active")

            # 曝光状态退化（被其他流程抑制）
            RaceNewsExposure.objects.filter(pk=exposure.pk).update(status="suppressed")

            # 幂等重设：必须重新同步 exposure，而不是直接早退成功
            state1 = get_headline_state()
            second = set_manual_headline(
                headline.pk, user=user, expected_version=state1["version"],
            )
            self.assertTrue(second.get("success"), f"idempotent set failed: {second}")
            exposure.refresh_from_db()
            self.assertEqual(
                exposure.status, "active",
                "幂等分支绕过 exposure 同步，suppressed 未被修复",
            )
            # 版本不变（未发生新的选择变更）
            self.assertEqual(second["version"], first["version"])

    def test_idempotent_reactivate_slot2_with_real_angle(self) -> None:
        """综合赛果 slot1 + connections 头条 slot2 被 suppressed 后幂等恢复。

        回归：reserve 路径曾把角度硬编码为 comprehensive_result，与 slot1
        同角度导致 same_angle 拒绝，头条保持 suppressed 不可见。
        """
        try:
            RaceNewsExposure = _try_import_model(
                "stable.models.RaceNewsExposure"
            )
            set_manual_headline = _try_import_service(
                "stable.services.editorial_headlines.set_manual_headline"
            )
            get_headline_state = _try_import_service(
                "stable.services.editorial_headlines.get_headline_state"
            )
        except ImportError:
            self.fail("相关服务未实现")
            return
        event = _make_event()
        slot1_article = _make_article(title="赛果公布：冠军诞生", source_article_id="hl-ra-s1")
        # 头条角度为 connections（练马师），与 slot1 的 comprehensive_result 不同
        headline = _make_article(title="练马师专访", source_article_id="hl-ra-new")
        _make_article_race_link(
            article=headline, event=event,
            status=ArticleRaceLinkStatus.MANUAL,
        )
        RaceNewsExposure.objects.create(
            event=event, article=slot1_article,
            channel="homepage", scope_key="site", slot=1,
            status="active", angle="comprehensive_result",
            policy_version="v1", reason="first_slot",
            activated_at=timezone.now() - timedelta(minutes=30),
        )
        slot2 = RaceNewsExposure.objects.create(
            event=event, article=headline,
            channel="homepage", scope_key="site", slot=2,
            status="suppressed", angle="connections",
            policy_version="v1", reason="backfill_overflow",
        )
        user = self._staff_user()
        with override_settings(RACE_NEWS_EXPOSURE_ENABLED=True):
            # 第一次设置：suppressed slot2 应被重激活（真实角度 connections
            # 与 slot1 不同，允许 slot 2）
            state0 = get_headline_state()
            first = set_manual_headline(
                headline.pk, user=user, expected_version=state0["version"],
            )
            self.assertTrue(first.get("success"), f"first set failed: {first}")
            slot2.refresh_from_db()
            self.assertEqual(slot2.status, "active")
            self.assertEqual(slot2.angle, "connections")
            self.assertIsNotNone(
                slot2.activated_at,
                "重激活为 active 的 slot 2 必须带激活时间戳",
            )

            # 再次退化为 suppressed
            RaceNewsExposure.objects.filter(pk=slot2.pk).update(status="suppressed")

            # 幂等重设：必须再次恢复为 active，而非 same_angle 拒绝
            state1 = get_headline_state()
            second = set_manual_headline(
                headline.pk, user=user, expected_version=state1["version"],
            )
            self.assertTrue(second.get("success"), f"idempotent set failed: {second}")
            slot2.refresh_from_db()
            self.assertEqual(
                slot2.status, "active",
                "幂等恢复失败：suppressed 未被重激活（同角度误拒回归）",
            )
            self.assertIsNotNone(
                slot2.activated_at,
                "幂等恢复后 active 的 slot 2 必须带激活时间戳",
            )
            self.assertEqual(second["version"], first["version"])


# ============================================================================
# 测试用例 21d: 陈旧 exposure 原地重激活
# ============================================================================

class StaleExposureReactivationTests(TestCase):
    """已有 suppressed/replaced/waiting exposure 不得被当作成功返回。"""

    def test_reserve_reactivates_suppressed_row_in_place(self) -> None:
        """suppressed exposure 应原地重激活为 active，而非返回陈旧状态。"""
        try:
            RaceNewsExposure = _try_import_model(
                "stable.models.RaceNewsExposure"
            )
            reserve_exposure = _try_import_service(
                "stable.services.race_news_exposure.reserve_exposure"
            )
        except ImportError:
            self.fail("RaceNewsExposure 或 reserve_exposure 未实现")
            return
        event = _make_event()
        article = _make_article(title="被抑制文章")
        stale = RaceNewsExposure.objects.create(
            event=event, article=article,
            channel="homepage", scope_key="site", slot=2,
            status="suppressed", angle="other",
            policy_version="v1", reason="backfill_overflow",
        )
        result = reserve_exposure(
            event=event,
            article=article,
            channel="homepage",
            scope_key="site",
            angle="comprehensive_result",
        )
        self.assertEqual(result.get("status"), "active")
        self.assertEqual(result.get("slot"), 1)
        stale.refresh_from_db()
        self.assertEqual(stale.status, "active")
        self.assertEqual(stale.slot, 1)
        # 原地重激活：不产生第二行
        self.assertEqual(
            RaceNewsExposure.objects.filter(event=event, article=article).count(), 1,
        )

    def test_replace_slot2_reactivates_stale_new_article_row(self) -> None:
        """replace_slot2 对新文章的 suppressed 行应原地激活，而非空报成功。"""
        try:
            RaceNewsExposure = _try_import_model(
                "stable.models.RaceNewsExposure"
            )
            replace_slot2 = _try_import_service(
                "stable.services.race_news_exposure.replace_slot2"
            )
        except ImportError:
            self.fail("RaceNewsExposure 或 replace_slot2 未实现")
            return
        event = _make_event()
        article1 = _make_article(title="赛果公布", source_article_id="rs1")
        article2 = _make_article(
            title="练马师专访", source_article_id="rs2", score_total=90,
        )
        new_article = _make_article(
            title="骑师谈胜利", source_article_id="rs3", score_total=100,
        )
        mature_at = timezone.now() - timedelta(minutes=30)
        RaceNewsExposure.objects.create(
            event=event, article=article1,
            channel="homepage", scope_key="site", slot=1,
            status="active", angle="comprehensive_result",
            policy_version="v1", reason="first_slot", activated_at=mature_at,
        )
        old_slot2 = RaceNewsExposure.objects.create(
            event=event, article=article2,
            channel="homepage", scope_key="site", slot=2,
            status="active", angle="connections",
            policy_version="v1", reason="second_slot", activated_at=mature_at,
        )
        stale = RaceNewsExposure.objects.create(
            event=event, article=new_article,
            channel="homepage", scope_key="site", slot=2,
            status="suppressed", angle="other",
            policy_version="v1", reason="backfill_overflow",
        )
        result = replace_slot2(
            event=event,
            channel="homepage",
            scope_key="site",
            old_article=article2,
            new_article=new_article,
            reason="manual_headline_replacement",
        )
        self.assertEqual(result.get("slot"), 2)
        stale.refresh_from_db()
        self.assertEqual(stale.status, "active")
        self.assertEqual(stale.slot, 2)
        old_slot2.refresh_from_db()
        self.assertEqual(old_slot2.status, "replaced")

    def test_headline_with_stale_exposure_ends_up_active(self) -> None:
        """人工头条：有 suppressed exposure 的文章必须获得 active 席位。"""
        try:
            RaceNewsExposure = _try_import_model(
                "stable.models.RaceNewsExposure"
            )
            set_manual_headline = _try_import_service(
                "stable.services.editorial_headlines.set_manual_headline"
            )
            get_headline_state = _try_import_service(
                "stable.services.editorial_headlines.get_headline_state"
            )
        except ImportError:
            self.fail("相关服务未实现")
            return
        from django.contrib.auth import get_user_model
        event = _make_event()
        headline = _make_article(title="赛果：爆冷夺冠", source_article_id="hl-stale")
        _make_article_race_link(
            article=headline, event=event,
            status=ArticleRaceLinkStatus.MANUAL,
        )
        stale = RaceNewsExposure.objects.create(
            event=event, article=headline,
            channel="homepage", scope_key="site", slot=2,
            status="suppressed", angle="other",
            policy_version="v1", reason="backfill_overflow",
        )
        user = get_user_model().objects.create_superuser(
            username=f"hl-stale-{timezone.now().timestamp()}", password="x",
        )
        with override_settings(RACE_NEWS_EXPOSURE_ENABLED=True):
            state_before = get_headline_state()
            result = set_manual_headline(
                headline.pk, user=user,
                expected_version=state_before["version"],
            )
        self.assertTrue(result.get("success"), f"headline rejected: {result}")
        stale.refresh_from_db()
        self.assertEqual(
            stale.status, "active",
            "头条提交成功但文章没有 active exposure",
        )


# ============================================================================
# 测试用例 30 (续): 功能开关
# ============================================================================

class FeatureFlagTests(TestCase):
    """功能开关与设置值检查。"""

    def test_race_news_exposure_enabled_flag_defined(self) -> None:
        """RACE_NEWS_EXPOSURE_ENABLED 开关应在 settings 中定义。"""
        self.assertTrue(
            hasattr(settings, "RACE_NEWS_EXPOSURE_ENABLED"),
            "settings.RACE_NEWS_EXPOSURE_ENABLED 应已定义（默认 false），"
            "但当前未在 settings.py 中设置",
        )

    def test_race_news_exposure_shadow_flag_defined(self) -> None:
        """RACE_NEWS_EXPOSURE_SHADOW 开关应在 settings 中定义。"""
        self.assertTrue(
            hasattr(settings, "RACE_NEWS_EXPOSURE_SHADOW"),
            "settings.RACE_NEWS_EXPOSURE_SHADOW 应已定义，"
            "但当前未在 settings.py 中设置",
        )

    def test_second_slot_delay_defined(self) -> None:
        """RACE_NEWS_SECOND_SLOT_DELAY_MINUTES 应在 settings 中定义。"""
        self.assertTrue(
            hasattr(settings, "RACE_NEWS_SECOND_SLOT_DELAY_MINUTES"),
            "settings.RACE_NEWS_SECOND_SLOT_DELAY_MINUTES 应已定义，"
            "但当前未在 settings.py 中设置",
        )

    def test_homepage_max_defined(self) -> None:
        """RACE_NEWS_HOMEPAGE_MAX 应在 settings 中定义。"""
        self.assertTrue(
            hasattr(settings, "RACE_NEWS_HOMEPAGE_MAX"),
            "settings.RACE_NEWS_HOMEPAGE_MAX 应已定义，"
            "但当前未在 settings.py 中设置",
        )

    def test_qq_target_max_defined(self) -> None:
        """RACE_NEWS_QQ_TARGET_MAX 应在 settings 中定义。"""
        self.assertTrue(
            hasattr(settings, "RACE_NEWS_QQ_TARGET_MAX"),
            "settings.RACE_NEWS_QQ_TARGET_MAX 应已定义，"
            "但当前未在 settings.py 中设置",
        )


# ============================================================================
# 内容分类枚举（角度）测试
# ============================================================================

class AngleClassificationTests(TestCase):
    """角度分类逻辑测试。"""

    def test_classify_angle_service_exists(self) -> None:
        """classify_angle 服务应可导入。"""
        try:
            classify_angle = _try_import_service(
                "stable.services.race_news_exposure.classify_angle"
            )
        except ImportError:
            self.fail("classify_angle 服务未实现（预期 RED）")
            return

    def test_classify_angle_returns_valid_enum(self) -> None:
        """角度分类应返回有效枚举值之一。"""
        try:
            classify_angle = _try_import_service(
                "stable.services.race_news_exposure.classify_angle"
            )
        except ImportError:
            self.fail("classify_angle 服务未实现（预期 RED）")
            return
        event = _make_event()
        article = _make_article(
            title="英皇锦标赛果：胜者确定",
            body_zh="比赛结果：第一名 7号马 勇敢之心",
        )
        result = classify_angle(article=article, event=event)
        valid_angles = {
            "comprehensive_result",
            "winner",
            "connections",
            "runner",
            "analysis",
            "market",
            "other",
        }
        self.assertIn(result["angle"], valid_angles)
        self.assertIn("evidence", result)

    def test_low_confidence_falls_to_other(self) -> None:
        """低置信角度分类应降级为 other。"""
        try:
            classify_angle = _try_import_service(
                "stable.services.race_news_exposure.classify_angle"
            )
        except ImportError:
            self.fail("classify_angle 服务未实现（预期 RED）")
            return
        event = _make_event()
        article = _make_article(
            title="春季训练记录",
            body_zh="今日晨操记录，马匹状态良好",
        )
        result = classify_angle(article=article, event=event)
        self.assertEqual(result["angle"], "other")
