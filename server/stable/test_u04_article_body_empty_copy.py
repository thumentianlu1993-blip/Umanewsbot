"""U04 新闻详情正文缺失文案：独立真实 GET 合同，仅使用合成记录。

固定 d6790dd2 上第一项预期因缺文案而 RED；本阶段仅提交源码，未执行。
不模拟 ORM/读取异常，不调用发布、抓取或第三方服务，不导入其他测试类。
"""
from html.parser import HTMLParser

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from stable.models import NewsArticle, SourceMode, SourceSite, WorkflowStatus


EMPTY_BODY_COPY = "本文暂无正文。"
BODY_FIELDS = (
    "rewrite_body_zh", "body_zh", "translated_body_zh",
    "body_ja_normalized", "body_ja_raw",
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
    """只解析真实 Client 响应，不在本地构造或渲染候选 HTML。"""

    VOID_TAGS = frozenset("area base br col embed hr img input link meta param source track wbr".split())

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
class U04ArticleBodyEmptyCopyTests(TestCase):
    def _article(self, label, *, bodies=None, manual_fields=(),
                 workflow=WorkflowStatus.PUBLISHED, web_published=True):
        now = timezone.now()
        values = {field: "" for field in BODY_FIELDS}
        values.update(bodies or {})
        return NewsArticle.objects.create(
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.LATEST,
            source_article_id=f"D044-SYNTHETIC-{label}",
            source_url=f"https://example.invalid/d044/{label}",
            title_ja=f"D044原始标题{label}",
            title_zh=f"D044公开标题{label}",
            summary_zh=f"D044独立摘要{label}",
            manually_edited_fields=list(manual_fields),
            workflow_status=workflow,
            published_at=now,
            published_to_web_at=now if web_published else None,
            **values,
        )

    def _get_without_article_mutation(self, article, *, expected_status=200):
        before = list(NewsArticle.objects.order_by("pk").values())
        response = self.client.get(reverse("public-article-detail", args=[article.pk]))
        self.assertEqual(response.status_code, expected_status)
        self.assertEqual(response.resolver_match.url_name, "public-article-detail")
        after = list(NewsArticle.objects.order_by("pk").values())
        self.assertTrue(before == after, "公开 GET 不应改变新闻完整字段或行集合")
        return response

    def _public_body(self, article):
        response = self._get_without_article_mutation(article)
        self.assertEqual(response.context["article"].pk, article.pk)
        self.assertEqual(response.context["article"].workflow_status, WorkflowStatus.PUBLISHED)
        self.assertIsNotNone(response.context["article"].published_to_web_at)
        self.assertTemplateUsed(response, "stable/public/detail.html")
        document = _Document(response.content.decode(response.charset))
        articles = [node for node in document.nodes if node.tag == "article" and node.has_class("article-detail")]
        self.assertEqual(len(articles), 1, "前件：唯一真实公开新闻详情")
        bodies = [node for node in document.nodes if node.tag == "div" and node.has_class("article-body")]
        self.assertEqual(len(bodies), 1, "前件：唯一原正文容器")
        self.assertTrue(bodies[0].inside(articles[0]))
        headings = [node for node in document.nodes if node.tag == "h1" and node.inside(articles[0])]
        self.assertEqual([node.text().strip() for node in headings], [article.effective_title])
        summaries = [node for node in document.nodes if node.has_class("article-lede") and node.inside(articles[0])]
        self.assertEqual([node.text().strip() for node in summaries], [article.effective_summary])
        return response, document, bodies[0]

    def test_empty_body_get_explains_missing_body_once_inside_original_container(self):
        article = self._article("EMPTY")
        self.assertTrue(all(getattr(article, field) == "" for field in BODY_FIELDS))
        self.assertEqual(article.effective_body, "", "前件：真实现存正文选择器为空，不模拟读取失败")
        response, document, body = self._public_body(article)
        self.assertEqual(response.context["article"].effective_body, "")
        paragraphs = [node for node in document.nodes if node.tag == "p" and node.text().strip() == EMPTY_BODY_COPY]
        self.assertEqual(len(paragraphs), 1, "U04：正文缺失说明 p 必须恰好一次")
        paragraph = paragraphs[0]
        self.assertTrue(paragraph.inside(body), "文案应在原 article-body 内，不能出现在推荐卡或摘要中")
        self.assertEqual(paragraph.attrs, {"class": "muted"})
        self.assertTrue(all(isinstance(part, str) for part in paragraph.parts), "文案只含纯文字，不添加错误码、链接或重试动作")
        self.assertEqual(response.content.decode(response.charset).count(EMPTY_BODY_COPY), 1)

    def test_existing_body_layers_keep_real_content_linebreaks_and_no_empty_copy(self):
        cases = [
            ("rewrite_body_zh", ()),
            ("body_zh", ("body_zh",)),
            ("body_zh", ()),
            ("translated_body_zh", ()),
            ("body_ja_normalized", ()),
            ("body_ja_raw", ()),
        ]
        for index, (field, manual_fields) in enumerate(cases):
            with self.subTest(field=field, manual=bool(manual_fields)):
                first = f"D044正文{index}第一行"
                second = f"D044正文{index}第二行 <em>正文按文本展示</em>"
                content = first + "\n" + second
                values = {field: content}
                if manual_fields:
                    values["rewrite_body_zh"] = "D044不应覆盖人工正文的改写层"
                article = self._article(f"BODY-{index}", bodies=values, manual_fields=manual_fields)
                self.assertEqual(article.effective_body, content)
                response, document, body = self._public_body(article)
                self.assertEqual(response.context["article"].effective_body, content)
                self.assertNotIn(EMPTY_BODY_COPY, response.content.decode(response.charset))
                self.assertIn(first, body.text())
                self.assertIn(second, body.text())
                self.assertTrue(any(node.tag == "br" and node.inside(body) for node in document.nodes))
                self.assertFalse(any(node.tag == "em" and node.inside(body) for node in document.nodes))
                self.assertIn("&lt;em&gt;正文按文本展示&lt;/em&gt;", response.content.decode(response.charset))

    def test_nonpublic_or_missing_web_publication_stays_404_without_empty_copy(self):
        cases = [
            self._article("PENDING", workflow=WorkflowStatus.PENDING_REVIEW),
            self._article("NO-WEB-TIME", web_published=False),
        ]
        for article in cases:
            with self.subTest(article=article.source_article_id):
                response = self._get_without_article_mutation(article, expected_status=404)
                html = response.content.decode(response.charset)
                self.assertNotIn(EMPTY_BODY_COPY, html)
                self.assertNotIn(article.title_zh, html)
                self.assertNotIn(article.summary_zh, html)
