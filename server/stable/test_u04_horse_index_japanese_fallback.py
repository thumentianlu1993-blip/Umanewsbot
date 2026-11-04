"""D078 U04：原名栏日文 fallback 独立测试源码，尚未执行。

真实 ORM/GET/身份与原卡片结构前件用 RuntimeError 标明 ERROR。
首新需求只比较唯一卡片的原名 p，不用搜索 input/title 的日文回显代验。
"""
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

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


NAME_FIELDS = ("original_name", "english_name", "japanese_name")
ORIGINAL_PLACEHOLDER = "资料整理中"


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


class _Document(HTMLParser):
    """只解析 Client 原响应，不创建或替换候选 HTML。"""

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
class U04HorseIndexJapaneseFallbackTests(TestCase):
    def _profile(self, label, *, status=HorseProfileStatus.PUBLISHED, names=None):
        expected = {field: "" for field in NAME_FIELDS}
        expected.update(names or {})
        _require(set(expected) == set(NAME_FIELDS), "only the existing three name fields")
        try:
            term = TermEntry(
                term_type=TermType.HORSE,
                source_language=SourceLanguage.JAPANESE,
                source_ja=f"D078-TERM-{label}",
                target_zh=f"D078中文合成马{label}",
                racing_region=RacingRegion.JAPAN,
                is_active=True,
            )
            term.full_clean()
            term.save()
            term.refresh_from_db()
            _require(term.pk is not None and term.target_zh == f"D078中文合成马{label}", "saved term identity")
            profile = HorseProfile(
                primary_term=term,
                display_name_zh=term.target_zh,
                racing_region=RacingRegion.JAPAN,
                review_status=status,
                country="",
                **expected,
            )
            profile.full_clean()
            profile.save()
            profile.refresh_from_db()
            _require(profile.pk is not None and profile.primary_term_id == term.pk, "saved profile/term identity")
            _require(profile.review_status == status and profile.display_name_zh == term.target_zh, "saved status/known Chinese name")
            _require(profile.display_name == term.target_zh, "title cannot stand in for Japanese original text")
            _require(profile.country == "" and all(getattr(profile, field) == value for field, value in expected.items()), "saved searchable values")
        except Exception as error:
            _precondition_error("real TermEntry/HorseProfile full_clean/save/refresh", error)
        return profile, expected

    def _listing(self, query):
        try:
            path = reverse("public-horse-index")
            _require(path == "/horses/", "canonical public horse index")
            response = self.client.get(path, {"q": query})
            _require(response.status_code == 200, "real list GET200, including nonpublic exclusion cases")
            _require(response.resolver_match.url_name == "public-horse-index", "real list resolver")
            _require("stable/public/horse_index.html" in [getattr(item, "name", None) for item in response.templates], "actual horse_index template")
            _require(response.context["filters"]["q"] == query, "actual q context")
            profiles = list(response.context["horse_profiles"])
            document = _Document(response.content.decode(response.charset))
            headings = [node for node in document.nodes if node.tag == "h1"]
            _require(len(headings) == 1 and headings[0].text().strip() == "马匹档案", "existing list h1")
        except Exception as error:
            _precondition_error("real list GET/resolver/template/context", error)
        return response, profiles, document

    def _public_card(self, profile, expected, *, query):
        response, profiles, document = self._listing(query)
        try:
            _require(len(profiles) == 1 and profiles[0].pk == profile.pk, "unique response profile pk")
            actual = profiles[0]
            _require(actual.review_status == HorseProfileStatus.PUBLISHED, "response profile published")
            _require(actual.display_name_zh == profile.display_name_zh, "response known Chinese name")
            _require(actual.country == "" and all(getattr(actual, field) == value for field, value in expected.items()), "response exact three name values")
            _require(all(getattr(actual, field) == 0 for field in ("starts_count", "wins_count", "seconds_count", "thirds_count")), "synthetic card has no race-record aggregates")
            cards = [node for node in document.nodes if node.tag == "article" and node.has_class("horse-card")]
            _require(len(cards) == 1, "unique original article.horse-card")
            card = cards[0]
            headings = [node for node in document.nodes if node.tag == "h2" and node.nearest("article") is card]
            _require(len(headings) == 1 and headings[0].has_class("horse-card-name"), "unique original card h2")
            links = headings[0].children("a")
            _require(len(links) == 1 and links[0].text().strip() == actual.display_name_zh, "known card title/link identity")
            href = actual.public_list_detail_url
            canonical = reverse("public-horse-detail", args=[actual.pk])
            _require(canonical == f"/horses/{actual.pk}/", "canonical profile detail path")
            _require(links[0].attrs.get("href") == href, "full href equals actual context href, including return_nav")
            parsed = urlsplit(href)
            _require(not parsed.scheme and not parsed.netloc and not parsed.fragment and parsed.path == canonical, "context href canonical pathname")
            _require(bool(parse_qs(parsed.query).get("return_nav")), "short q retains actual return_nav token")
            originals = [node for node in document.nodes if node.tag == "p" and node.has_class("horse-card-original") and node.nearest("article") is card]
            _require(len(originals) == 1, "unique existing original-name p inside same card")
        except Exception as error:
            _precondition_error("real unique profile/card/h2/href/original-p identity", error)
        return response, document, actual, card, originals[0]

    def _japanese_query(self, profile, expected):
        query = expected["japanese_name"]
        _require(bool(query) and query == profile.japanese_name, "known persisted Japanese query")
        _require(all(query not in value for value in (profile.display_name_zh, expected["original_name"], expected["english_name"], profile.country)), "Japanese q cannot match another searchable OR field")
        return query

    def _assert_card_protection(self, response, document, actual, card, original):
        self.assertTrue(all(isinstance(part, str) for part in original.parts), "original-name p stays pure text")
        grids = [node for node in document.nodes if node.tag == "section" and node.attrs.get("aria-label") == "马匹列表"]
        self.assertEqual(len(grids), 1)
        self.assertTrue(grids[0].has_class("horse-grid"))
        self.assertIs(card.nearest("section"), grids[0])
        forms = [node for node in document.nodes if node.tag == "form" and node.nearest("article") is card]
        self.assertEqual(len(forms), 1)
        self.assertEqual(forms[0].attrs.get("action"), reverse("public-horse-follow", args=[actual.pk]))
        self.assertEqual(forms[0].attrs.get("method", "").lower(), "post")
        inputs = [node for node in document.nodes if node.tag == "input" and node.nearest("form") is forms[0]]
        self.assertEqual([node.attrs.get("value") for node in inputs if node.attrs.get("name") == "next"], [response.wsgi_request.get_full_path()])
        self.assertEqual([node.attrs.get("value") for node in inputs if node.attrs.get("name") == "include_descendants"], ["1"])
        badges = [node for node in card.children("p") if node.has_class("muted")]
        self.assertEqual([node.text().strip() for node in badges], [actual.public_completeness_badge])
        records = [node for node in card.children("div") if node.has_class("horse-record")]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].attrs.get("aria-label"), "战绩")
        self.assertEqual([node.text().strip() for node in records[0].children("span")], ["0 战", "0 亚", "0 季"])
        self.assertEqual([node.text().strip() for node in records[0].children("b")], ["0 冠"])

    def test_japanese_only_name_is_shown_in_original_cell(self):
        profile, expected = self._profile("JAPANESE", names={"japanese_name": "D078日文名カナのみ"})
        query = self._japanese_query(profile, expected)
        response, document, actual, card, original = self._public_card(profile, expected, query=query)
        # 首新需求；之前全为真实前件ERROR，不以input/title的Japanese回显冒充通过。
        self.assertEqual(original.text().strip(), expected["japanese_name"], "U04：已有日文名应显示在原名栏；旧模板预计显示资料整理中")
        self._assert_card_protection(response, document, actual, card, original)

    def test_original_and_english_names_keep_precedence(self):
        cases = (
            ("ORIGINAL", {"original_name": "D078-Original-First", "english_name": "D078-English-Second", "japanese_name": "D078日文名優先一"}, "D078-Original-First"),
            ("ENGLISH", {"english_name": "D078-English-First", "japanese_name": "D078日文名優先二"}, "D078-English-First"),
        )
        for label, names, selected in cases:
            with self.subTest(precedence=label):
                profile, expected = self._profile(label, names=names)
                _require(len([value for value in expected.values() if value]) == len(set(value for value in expected.values() if value)), "different nonempty precedence values")
                response, document, actual, card, original = self._public_card(profile, expected, query=self._japanese_query(profile, expected))
                self.assertEqual(original.text().strip(), selected)
                self._assert_card_protection(response, document, actual, card, original)

    def test_all_empty_names_keep_placeholder_and_card_structure(self):
        profile, expected = self._profile("ALL-EMPTY")
        _require(not any(expected.values()), "all three names empty, known Chinese query required")
        response, document, actual, card, original = self._public_card(profile, expected, query=profile.display_name_zh)
        self.assertEqual(original.text().strip(), ORIGINAL_PLACEHOLDER)
        self._assert_card_protection(response, document, actual, card, original)

    def test_draft_and_hidden_names_stay_excluded_from_list_get200(self):
        for status in (HorseProfileStatus.DRAFT, HorseProfileStatus.HIDDEN):
            with self.subTest(status=status):
                profile, expected = self._profile(f"NONPUBLIC-{status}", status=status, names={"japanese_name": f"D078非公開日文{status}"})
                query = self._japanese_query(profile, expected)
                response, profiles, document = self._listing(query)
                self.assertNotIn(profile.pk, [actual.pk for actual in profiles])
                self.assertEqual(profiles, [])
                self.assertEqual([node for node in document.nodes if node.tag == "article" and node.has_class("horse-card")], [])
                empty = [node for node in document.nodes if node.tag == "p" and node.has_class("empty-state")]
                self.assertEqual([node.text().strip() for node in empty], ["没有找到符合搜索条件的已发布马匹资料。"])
