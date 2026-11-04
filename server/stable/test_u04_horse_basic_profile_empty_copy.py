"""D073 U04：马匹基础资料空栏的独立真实 GET 合同，仅准备源码。

固定 bb878 原模板的主需求断言预计因缺少 p 而 RED；本模块尚未执行。
所有身份/ORM/路由/context/hero 前件失败均为带标记的 RuntimeError(ERROR)，
不能当需求 RED。没有 mock、模板替换、旧 TestCase 导入或真实来源依赖。
"""
from html.parser import HTMLParser

from django.test import TestCase, override_settings
from django.urls import reverse

from stable.models import (
    HorseProfile,
    HorseProfileStatus,
    RacingRegion,
    SourceLanguage,
    TermEntry,
    TermType,
)


EMPTY_BASIC_COPY = "本栏暂无国家/地区、马主、练马师、生产牧场及简介资料。"
BASIC_FIELDS = ("country", "owner_name", "trainer_name", "breeder_name", "intro")
BASIC_LABELS = {
    "country": "国家/地区",
    "owner_name": "马主",
    "trainer_name": "练马师",
    "breeder_name": "生产牧场",
}


def _require(condition, detail):
    if not condition:
        raise RuntimeError(f"TEST_PRECONDITION_FAILED: {detail}")


def _precondition_error(detail, error):
    if isinstance(error, RuntimeError) and str(error).startswith("TEST_PRECONDITION_FAILED:"):
        raise error
    raise RuntimeError(f"TEST_PRECONDITION_FAILED: {detail}") from error


class _Node:
    def __init__(self, tag, attrs=(), parent=None):
        self.tag = tag
        self.attr_items = tuple(attrs)
        self.attrs = dict(attrs)
        self.parent = parent
        self.parts = []

    def text(self):
        return "".join(part if isinstance(part, str) else part.text() for part in self.parts)

    def has_class(self, name):
        return name in self.attrs.get("class", "").split()

    def children(self, tag):
        return [part for part in self.parts if isinstance(part, _Node) and part.tag == tag]

    def nearest(self, tag):
        node = self.parent
        while node is not None:
            if node.tag == tag:
                return node
            node = node.parent
        return None

    def inside(self, ancestor):
        node = self.parent
        while node is not None:
            if node is ancestor:
                return True
            node = node.parent
        return False


class _Document(HTMLParser):
    """仅解析实际 Client 响应；不创建、替换、过滤候选 HTML。"""

    VOID_TAGS = frozenset("area base br col embed hr img input link meta param source track wbr".split())

    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = _Node("document")
        self.stack = [self.root]
        self.nodes = []
        self.feed(html)
        self.close()

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, attrs, self.stack[-1])
        self.stack[-1].parts.append(node)
        self.nodes.append(node)
        if tag not in self.VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        node = _Node(tag, attrs, self.stack[-1])
        self.stack[-1].parts.append(node)
        self.nodes.append(node)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].parts.append(data)


@override_settings(ALLOWED_HOSTS=["testserver"])
class U04HorseBasicProfileEmptyCopyTests(TestCase):
    def _profile(self, label, *, status=HorseProfileStatus.PUBLISHED, values=None):
        expected = {field: "" for field in BASIC_FIELDS}
        expected.update(values or {})
        _require(set(expected) == set(BASIC_FIELDS), "fixture contains only existing five basic fields")
        try:
            term = TermEntry(
                term_type=TermType.HORSE,
                source_language=SourceLanguage.JAPANESE,
                source_ja=f"D073-SYNTHETIC-{label}",
                target_zh=f"D073合成马{label}",
                racing_region=RacingRegion.JAPAN,
                is_active=True,
            )
            term.full_clean()
            term.save()
            profile = HorseProfile(
                primary_term=term,
                display_name_zh=term.target_zh,
                original_name=term.source_ja,
                racing_region=RacingRegion.JAPAN,
                review_status=status,
                **expected,
            )
            profile.full_clean()
            profile.save()
            profile.refresh_from_db()
            _require(profile.pk is not None and profile.review_status == status, "saved profile identity/status")
            _require(profile.display_name_zh == term.target_zh, "saved known horse name")
            _require(all(getattr(profile, field) == value for field, value in expected.items()), "saved basic values")
        except Exception as error:
            _precondition_error("real ORM/full_clean/save/refresh fixture", error)
        return profile, expected

    def _response(self, profile, *, expected_status):
        try:
            path = reverse("public-horse-detail", args=[profile.pk])
            _require(path == f"/horses/{profile.pk}/", "canonical public horse reverse target")
            response = self.client.get(path)
            _require(response.status_code == expected_status, "real GET status")
            _require(response.resolver_match.url_name == "public-horse-detail", "real horse resolver")
        except Exception as error:
            _precondition_error("real public horse route/GET", error)
        return response

    def _public(self, profile, expected):
        response = self._response(profile, expected_status=200)
        try:
            names = [getattr(template, "name", None) for template in response.templates]
            _require("stable/public/horse_detail.html" in names, "actual horse_detail template")
            actual = response.context["profile"]
            _require(actual.pk == profile.pk, "response profile pk")
            _require(actual.review_status == HorseProfileStatus.PUBLISHED, "response profile is published")
            _require(all(getattr(actual, field) == value for field, value in expected.items()), "response five field values")
            html = response.content.decode(response.charset)
            document = _Document(html)
            heroes = [node for node in document.nodes if node.tag == "section" and node.has_class("horse-hero")]
            _require(len(heroes) == 1, "unique existing horse hero")
            headings = [node for node in document.nodes if node.tag == "h1" and node.inside(heroes[0])]
            _require(len(headings) == 1 and headings[0].text().strip() == profile.display_name_zh, "unique hero h1 known identity")
        except Exception as error:
            _precondition_error("real template/context/hero", error)
        return response, document, heroes[0]

    def _basic_section(self, document):
        sections = [
            node for node in document.nodes
            if node.tag == "section" and node.has_class("panel")
            and [child.text().strip() for child in node.children("h2")] == ["基础资料"]
        ]
        self.assertEqual(len(sections), 1, "本栏必须是唯一基础资料 section.panel")
        return sections[0]

    def test_published_empty_basic_fields_has_scoped_copy(self):
        profile, expected = self._profile("EMPTY")
        response, document, hero = self._public(profile, expected)
        _require(not any(getattr(response.context["profile"], field) for field in BASIC_FIELDS), "five response fields all false")

        # 之前全部是 RuntimeError 前件；不要先要求当前尚不存在的基础资料 panel。
        paragraphs = [node for node in document.nodes if node.tag == "p" and node.text().strip() == EMPTY_BASIC_COPY]
        self.assertEqual(len(paragraphs), 1, "U04：本栏缺资料说明 p 必须恰好一次；原模板预计0!=1")
        paragraph = paragraphs[0]
        panel = paragraph.nearest("section")
        self.assertIsNotNone(panel)
        self.assertTrue(panel.has_class("panel"))
        self.assertIs(panel, self._basic_section(document))
        headings = [node for node in document.nodes if node.tag == "h2" and node.nearest("section") is panel]
        self.assertEqual([node.text().strip() for node in headings], ["基础资料"])
        self.assertEqual(paragraph.attrs, {"class": "muted"})
        self.assertEqual(paragraph.attr_items, (("class", "muted"),))
        self.assertTrue(all(isinstance(part, str) for part in paragraph.parts), "说明仅纯文字")
        self.assertFalse(paragraph.inside(hero))
        self.assertIsNone(paragraph.nearest("form"))
        for node in document.nodes:
            if node.has_class("record-list") or node.has_class("related-grid") or node.has_class("horse-stats"):
                self.assertFalse(paragraph.inside(node))
        self.assertEqual(response.content.decode(response.charset).count(EMPTY_BASIC_COPY), 1)

    def test_each_nonempty_basic_field_keeps_its_scoped_value_without_empty_copy(self):
        values = {
            "country": "日本",
            "owner_name": "D073合成马主",
            "trainer_name": "D073合成练马师",
            "breeder_name": "D073合成生产牧场",
            "intro": "D073合成简介正文",
        }
        for field, value in values.items():
            with self.subTest(field=field):
                profile, expected = self._profile(f"ONLY-{field}", values={field: value})
                response, document, _hero = self._public(profile, expected)
                _require(sum(bool(getattr(response.context["profile"], item)) for item in BASIC_FIELDS) == 1, "exactly one basic field true")
                panel = self._basic_section(document)
                grids = [node for node in document.nodes if node.tag == "div" and node.has_class("race-meta-grid") and node.nearest("section") is panel]
                self.assertEqual(len(grids), 1)
                if field == "intro":
                    intros = [node for node in document.nodes if node.tag == "p" and node.has_class("horse-intro") and node.nearest("section") is panel]
                    self.assertEqual([node.text().strip() for node in intros], [value])
                else:
                    cells = [node for node in grids[0].children("div") if [label.text().strip() for label in node.children("span")] == [BASIC_LABELS[field]]]
                    self.assertEqual(len(cells), 1, "标签/值必须在本栏grid，不能借hero同名值通过")
                    self.assertIs(cells[0].nearest("section"), panel)
                    self.assertEqual([node.text().strip() for node in cells[0].children("b")], [value])
                self.assertFalse(any(node.tag == "p" and node.inside(panel) and node.text().strip() == EMPTY_BASIC_COPY for node in document.nodes))
                self.assertNotIn(EMPTY_BASIC_COPY, response.content.decode(response.charset))

    def test_empty_basic_fields_preserve_identity_navigation_form_and_record_empty_state(self):
        profile, expected = self._profile("PROTECT")
        response, document, hero = self._public(profile, expected)
        self.assertEqual([node.text().strip() for node in document.nodes if node.tag == "h1" and node.inside(hero)], [profile.display_name_zh])
        actions = [node for node in document.nodes if node.tag == "nav" and node.attrs.get("aria-label") == "马匹操作"]
        self.assertEqual(len(actions), 1)
        return_links = [node for node in actions[0].children("a") if node.attrs.get("href") == response.context["public_return_url"]]
        self.assertEqual(len(return_links), 1)
        self.assertEqual(return_links[0].attrs.get("href"), reverse("public-horse-index"))
        forms = [node for node in document.nodes if node.tag == "form" and node.attrs.get("action") == reverse("public-horse-follow", args=[profile.pk])]
        self.assertEqual(len(forms), 1)
        self.assertEqual(forms[0].attrs.get("method", "").lower(), "post")
        next_fields = [node for node in document.nodes if node.tag == "input" and node.inside(forms[0]) and node.attrs.get("name") == "next"]
        self.assertEqual(len(next_fields), 1)
        self.assertEqual(next_fields[0].attrs.get("value"), response.context["public_detail_current_url"])
        _require(not response.context["race_records"], "synthetic horse has no race records")
        record_paragraphs = [node for node in document.nodes if node.tag == "p" and node.text().strip() == "暂无参赛履历。"]
        self.assertEqual(len(record_paragraphs), 1)
        record_panel = record_paragraphs[0].nearest("section")
        self.assertIsNotNone(record_panel)
        self.assertTrue(record_panel.has_class("panel"))
        self.assertEqual([node.text().strip() for node in record_panel.children("h2")], ["参赛履历"])

    def test_nonpublic_empty_basic_profiles_stay_404_without_copy(self):
        for status in (HorseProfileStatus.DRAFT, HorseProfileStatus.HIDDEN):
            with self.subTest(status=status):
                profile, _expected = self._profile(f"NONPUBLIC-{status}", status=status)
                response = self._response(profile, expected_status=404)
                self.assertNotIn(EMPTY_BASIC_COPY, response.content.decode(response.charset))
