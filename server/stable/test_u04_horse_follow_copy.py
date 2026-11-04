"""U04 默认关注说明：真实 Client 合同测试，仅使用合成资料。

第一组在固定 D972 预期因缺少说明段落而 RED；其余组保护既有行为。
本模块自包含，不导入其他测试类，也不 mock producer 或公开 feed。
"""
from html.parser import HTMLParser

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from stable.models import (
    ArticleHorseLink,
    ArticleHorseLinkStatus,
    HorseFollow,
    HorseProfile,
    HorseProfileStatus,
    NewsArticle,
    RacingRegion,
    SourceLanguage,
    SourceMode,
    SourceSite,
    TermEntry,
    TermType,
    WorkflowStatus,
)
from stable.services.horse_profiles import (
    FOLLOW_COOKIE_NAME,
    signed_follow_token,
    token_hash_from_cookie,
)


FOLLOW_COPY = (
    "此关注仅作站内新闻聚合：可在“我的关注”浏览这匹马及两代内后代已收录的公开新闻。"
)


class _Node:
    def __init__(self, tag, attrs=(), parent=None):
        self.tag = tag
        self.attrs = dict(attrs)
        self.parent = parent
        self.parts = []

    def text(self):
        return "".join(part if isinstance(part, str) else part.text() for part in self.parts)

    def has_class(self, name):
        return name in self.attrs.get("class", "").split()

    def inside(self, ancestor):
        parent = self.parent
        while parent is not None:
            if parent is ancestor:
                return True
            parent = parent.parent
        return False


class _Document(HTMLParser):
    """仅解析实际响应，保留段落与 form 的真实祖先关系。"""

    VOID_TAGS = frozenset(
        "area base br col embed hr img input link meta param source track wbr".split()
    )

    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = _Node("document")
        self.stack = [self.root]
        self.nodes = []
        self.feed(html)
        self.close()

    def _start(self, tag, attrs):
        node = _Node(tag, attrs, self.stack[-1])
        self.stack[-1].parts.append(node)
        self.nodes.append(node)
        return node

    def handle_starttag(self, tag, attrs):
        node = self._start(tag, attrs)
        if tag not in self.VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self._start(tag, attrs)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].parts.append(data)


@override_settings(ALLOWED_HOSTS=["testserver"])
class U04HorseFollowCopyTests(TestCase):
    def _profile(self, label, *, parent=None, status=HorseProfileStatus.PUBLISHED):
        term = TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language=SourceLanguage.JAPANESE,
            source_ja=f"D038-SYNTHETIC-HORSE-{label}",
            target_zh=f"D038合成马{label}",
            racing_region=RacingRegion.JAPAN,
            is_active=True,
        )
        return HorseProfile.objects.create(
            primary_term=term,
            display_name_zh=term.target_zh,
            original_name=term.source_ja,
            racing_region=RacingRegion.JAPAN,
            review_status=status,
            sire_horse_profile=parent,
        )

    def _article(self, label, *, workflow=WorkflowStatus.PUBLISHED, web_published=True):
        now = timezone.now()
        marker = f"D038-SYNTHETIC-NEWS-{label}-ONLY"
        return NewsArticle.objects.create(
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.LATEST,
            source_article_id=f"d038-synthetic-{label}",
            source_language=SourceLanguage.JAPANESE,
            racing_region=RacingRegion.JAPAN,
            source_url=f"https://example.invalid/d038/{label}",
            title_ja=marker,
            title_zh=marker,
            translated_title_zh=marker,
            body_ja_raw="D038 synthetic contract fixture.",
            body_ja_normalized="D038 synthetic contract fixture.",
            body_zh="D038合成合同正文。",
            translated_body_zh="D038合成合同正文。",
            summary_zh="D038合成合同摘要。",
            translated_summary_zh="D038合成合同摘要。",
            published_at=now,
            published_to_web_at=now if web_published else None,
            workflow_status=workflow,
        )

    def _get_without_follow_mutation(self, url):
        before = list(HorseFollow.objects.order_by("pk").values())
        cookie = self.client.cookies.get(FOLLOW_COOKIE_NAME)
        cookie_before = cookie.value if cookie is not None else None
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, "前件：真实 GET 必须成功")
        after = list(HorseFollow.objects.order_by("pk").values())
        self.assertTrue(before == after, "GET 改变了完整 HorseFollow 字段或行集合")
        self.assertTrue(
            FOLLOW_COOKIE_NAME not in response.cookies,
            "GET 不应创建/旋转关注 Cookie；正常 CSRF Cookie 允许",
        )
        cookie = self.client.cookies.get(FOLLOW_COOKIE_NAME)
        cookie_after = cookie.value if cookie is not None else None
        self.assertTrue(cookie_before == cookie_after, "GET 改变了客户端关注 Cookie")
        return response

    def _follow_form(self, response, profile, *, following):
        self.assertEqual(response.context["profile"].pk, profile.pk)
        self.assertEqual(response.context["profile"].review_status, HorseProfileStatus.PUBLISHED)
        self.assertIs(response.context["is_following"], following)
        document = _Document(response.content.decode(response.charset))
        forms = [
            node for node in document.nodes
            if node.tag == "form"
            and node.attrs.get("action") == reverse("public-horse-follow", args=[profile.pk])
        ]
        self.assertEqual(len(forms), 1, "前件：唯一真实关注 form")
        form = forms[0]
        self.assertEqual(form.attrs.get("method", "").lower(), "post")
        fields = [node for node in document.nodes if node.tag == "input" and node.inside(form)]
        buttons = [node for node in document.nodes if node.tag == "button" and node.inside(form)]
        self.assertEqual(len(buttons), 1)
        button = buttons[0]
        self.assertTrue(button.has_class("horse-follow-btn"))
        self.assertEqual(button.attrs.get("type"), "submit")
        csrf = [field for field in fields if field.attrs.get("name") == "csrfmiddlewaretoken"]
        self.assertEqual(len(csrf), 1, "前件：原 CSRF hidden 保留")
        self.assertTrue(bool(csrf[0].attrs.get("value")), "前件：CSRF 值存在，不输出其值")
        next_fields = [field for field in fields if field.attrs.get("name") == "next"]
        self.assertEqual(len(next_fields), 1)
        self.assertEqual(next_fields[0].attrs.get("value"), response.context["public_detail_current_url"])
        descendants = [field for field in fields if field.attrs.get("name") == "include_descendants"]
        if following:
            self.assertTrue(button.has_class("active"))
            self.assertEqual(button.text().strip(), "★ 已关注")
            self.assertEqual(button.attrs.get("name"), "intent")
            self.assertEqual(button.attrs.get("value"), "unfollow")
            self.assertEqual(descendants, [])
        else:
            self.assertFalse(button.has_class("active"))
            self.assertEqual(button.text().strip(), "☆ 关注")
            self.assertNotIn("name", button.attrs)
            self.assertEqual(len(descendants), 1)
            self.assertEqual(descendants[0].attrs.get("type"), "hidden")
            self.assertEqual(descendants[0].attrs.get("value"), "1")
        return document, form, fields

    def test_new_follow_get_explains_default_aggregation_once_inside_hero(self):
        profile = self._profile("NEW")
        self.assertTrue(FOLLOW_COOKIE_NAME not in self.client.cookies)
        response = self._get_without_follow_mutation(profile.public_path)
        document, form, _fields = self._follow_form(response, profile, following=False)
        heroes = [node for node in document.nodes if node.has_class("horse-hero-main")]
        self.assertEqual(len(heroes), 1, "前件：唯一真实 horse-hero-main")
        # 以上真实状态/context/form 均成立后，缺少新说明才是本组预期 RED。
        paragraphs = [
            node for node in document.nodes
            if node.tag == "p" and node.text().strip() == FOLLOW_COPY
        ]
        self.assertEqual(len(paragraphs), 1, "U04：默认关注说明 p 必须恰好一次")
        paragraph = paragraphs[0]
        self.assertTrue(paragraph.inside(heroes[0]), "说明必须在 horse-hero-main 内")
        self.assertFalse(paragraph.inside(form), "不改变既有 form 内容")
        self.assertEqual(paragraph.attrs, {"class": "muted"})
        self.assertTrue(all(isinstance(part, str) for part in paragraph.parts), "说明只含纯文本")
        self.assertEqual(response.content.decode(response.charset).count(FOLLOW_COPY), 1)

    def test_existing_follow_with_historical_options_keeps_fields_and_no_default_copy(self):
        profile = self._profile("HISTORICAL")
        signed_token = signed_follow_token()
        token_hash = token_hash_from_cookie(signed_token)
        follow = HorseFollow.objects.create(
            token_hash=token_hash,
            horse_profile=profile,
            include_descendants=False,
            descendant_depth=1,
        )
        self.client.cookies[FOLLOW_COOKIE_NAME] = signed_token
        before = HorseFollow.objects.filter(pk=follow.pk).values().get()
        response = self._get_without_follow_mutation(profile.public_path)
        self._follow_form(response, profile, following=True)
        self.assertTrue(FOLLOW_COPY not in response.content.decode(response.charset), "历史关注不冒默认两代保证")
        after = HorseFollow.objects.filter(pk=follow.pk).values().get()
        self.assertTrue(before == after, "历史关注所有字段必须逐值保持，不只比较 count")
        self.assertFalse(after["include_descendants"])
        self.assertEqual(after["descendant_depth"], 1)

    def test_real_form_post_preserves_depth_two_and_actual_public_follow_feed(self):
        parent = self._profile("PARENT")
        first = self._profile("GENERATION1", parent=parent)
        second = self._profile("GENERATION2", parent=first)
        third = self._profile("GENERATION3", parent=second)
        hidden = self._profile("HIDDEN", parent=parent, status=HorseProfileStatus.HIDDEN)
        positives = [
            (parent, self._article("PARENT"), ArticleHorseLinkStatus.MANUAL),
            (first, self._article("FIRST"), ArticleHorseLinkStatus.AUTO),
            (second, self._article("SECOND"), ArticleHorseLinkStatus.MANUAL),
        ]
        negatives = [
            (third, self._article("THIRD"), ArticleHorseLinkStatus.MANUAL),
            (hidden, self._article("HIDDEN"), ArticleHorseLinkStatus.MANUAL),
            (parent, self._article("CANDIDATE"), ArticleHorseLinkStatus.CANDIDATE),
            (parent, self._article("UNPUBLISHED", workflow=WorkflowStatus.PENDING_REVIEW), ArticleHorseLinkStatus.MANUAL),
            (parent, self._article("NO_WEB_TIME", web_published=False), ArticleHorseLinkStatus.MANUAL),
        ]
        cases = positives + negatives
        self.assertEqual(len({article.pk for _profile, article, _status in cases}), 8)
        self.assertEqual(len({article.title_zh for _profile, article, _status in cases}), 8)
        self.assertLess(len(cases), 40, "前件：所有 distinct 正反例均远低于 feed limit")
        for profile, article, status in cases:
            ArticleHorseLink.objects.create(horse_profile=profile, article=article, status=status)
        initial = self._get_without_follow_mutation(parent.public_path)
        _document, form, fields = self._follow_form(initial, parent, following=False)
        # 使用真实页面 fields POST；本组不提前断言新文案，以隔离唯一缺文案 RED。
        data = {field.attrs["name"]: field.attrs.get("value", "") for field in fields if field.attrs.get("name")}
        self.assertEqual(data["include_descendants"], "1")
        response = self.client.post(form.attrs["action"], data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], data["next"])
        self.assertTrue(FOLLOW_COOKIE_NAME in response.cookies, "真实 POST 应产生匿名关注 Cookie")
        cookie = self.client.cookies.get(FOLLOW_COOKIE_NAME)
        self.assertTrue(cookie is not None)
        token_hash = token_hash_from_cookie(cookie.value)
        self.assertEqual(HorseFollow.objects.count(), 1)
        follow = HorseFollow.objects.get(token_hash=token_hash, horse_profile=parent)
        self.assertTrue(follow.include_descendants)
        self.assertEqual(follow.descendant_depth, 2)
        feed = self._get_without_follow_mutation(reverse("public-horse-follows"))
        self.assertContains(feed, "我的关注")
        actual_ids = {entry["article"].pk for entry in feed.context["followed_entries"]}
        self.assertEqual(actual_ids, {article.pk for _profile, article, _status in positives})
        html = feed.content.decode(feed.charset)
        for _profile, article, _status in positives:
            with self.subTest(visible=article.title_zh):
                self.assertTrue(article.title_zh in html, "公开父/一二代文章标记应在真实 feed 中")
        for _profile, article, _status in negatives:
            with self.subTest(excluded=article.title_zh):
                self.assertTrue(article.title_zh not in html, "第三代/hidden/candidate/未公开独立标记不得泄漏")
