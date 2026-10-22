"""D003 待运行 Client 契约；合成数据，仅在隔离 django profile 执行。

不继承旧测试类，不 mock 页面/查询/签名 producer。目标 RED 必须是空态
缺少恢复文案/链接；setup、签名、301、环境失败均不是该业务 RED。
"""

from datetime import date, datetime, timezone as datetime_timezone
from html.parser import HTMLParser
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from stable.models import (
    RaceEvent,
    RaceEventPriority,
    RaceEventProductCanonicalLink,
    RaceEventResult,
    RaceEventStatus,
    RaceEventVisibility,
    RacingRegion,
)
from stable.services.race_calendar import (
    decode_race_calendar_cursor,
    encode_race_calendar_cursor,
)
from stable.services.race_public_time import public_time
from stable.views import _public_nav_token, _public_read_nav


TODAY = date(2026, 10, 17)
NOW = datetime(2026, 10, 17, 4, tzinfo=datetime_timezone.utc)
EMPTY_TEXT = "当前列表暂无可展示的已发布赛事。"
RESET_TEXT = "重置筛选，返回默认赛事列表"
RESET_HINT = "重置后按赛事日历的默认规则显示。"
OLD_EMPTY_TEXT = "暂无符合条件的赛事。"


class _Links(HTMLParser):
    """提取实际 DOM 链接，不以预设 href 代替页面输出。"""

    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.current = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            values = dict(attrs)
            self.current = {"href": values.get("href", ""),
                            "class": values.get("class", "").split(), "text": ""}

    def handle_data(self, data):
        if self.current is not None:
            self.current["text"] += data

    def handle_endtag(self, tag):
        if tag == "a" and self.current is not None:
            self.current["text"] = self.current["text"].strip()
            self.links.append(self.current)
            self.current = None


@override_settings(
    TIME_ZONE="Asia/Shanghai",
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class CalendarEmptyFilterRecoveryTests(TestCase):
    def setUp(self):
        self.url = reverse("public-race-calendar")
        self.serial = 0
        for target, value in (
            ("stable.views.timezone.localdate", TODAY),
            ("stable.views.timezone.now", NOW),
        ):
            controlled = patch(target, return_value=value)
            controlled.start()
            self.addCleanup(controlled.stop)

    def _event(self, **changes):
        self.serial += 1
        values = dict(
            year=TODAY.year, slug=f"d003-synthetic-{self.serial}",
            original_name=f"D003 Synthetic {self.serial}",
            chinese_name=f"合成恢复赛事{self.serial}",
            country_region=RacingRegion.JAPAN, racecourse="合成赛场",
            surface="turf", grade_text="G3", normalized_grade="G3",
            timezone_name="Asia/Shanghai", local_date=TODAY,
            priority=RaceEventPriority.P2, status=RaceEventStatus.SCHEDULED,
            visibility_status=RaceEventVisibility.PUBLISHED,
        )
        values.update(changes)
        return RaceEvent.objects.create(**values)

    def _get(self, **params):
        response = self.client.get(self.url, params)
        self.assertEqual(response.status_code, 200, "前件失败：此请求必须直接得到页面")
        return response

    def _ids(self, response):
        return [event.pk for group in response.context["groups"] for event in group["events"]]

    def _links(self, response):
        return _Links(response.content.decode("utf-8")).links

    def _empty(self, response):
        self.assertEqual(self._ids(response), [], "前件失败：筛选必须实际为空")
        self.assertFalse(any("cal-card" in link["class"] for link in self._links(response)))

    def _reset_href(self, response):
        self._empty(response)
        self.assertContains(response, EMPTY_TEXT)
        self.assertContains(response, RESET_HINT)
        self.assertNotContains(response, "重置后显示默认日期窗口内的已发布赛事")
        links = [link for link in self._links(response) if link["text"] == RESET_TEXT]
        self.assertEqual(len(links), 1, "目标 RED：空态缺少唯一重置链接")
        href = links[0]["href"]
        self.assertEqual(href, self.url + "?tab=all")
        parts = urlsplit(href)
        self.assertEqual((parts.scheme, parts.netloc, parts.path), ("", "", self.url))
        self.assertEqual(parse_qs(parts.query), {"tab": ["all"]})
        return href

    def _recover(self, response, event):
        href = self._reset_href(response)
        recovered = self.client.get(href)
        self.assertEqual(recovered.status_code, 200)
        self.assertEqual(recovered.context["filters"], {
            "tab": "all", "region": "", "grade": "", "when": "", "year": "",
            "q": "", "cursor": "", "direction": "",
        })
        self.assertIn(event.pk, self._ids(recovered))
        self.assertContains(recovered, event.chinese_name)
        all_tabs = [link for link in self._links(recovered)
                    if link["text"] == "全部" and "active" in link["class"]]
        self.assertTrue(any(parse_qs(urlsplit(link["href"]).query).get("tab") == ["all"]
                            for link in all_tabs))
        self.assertNotContains(recovered, RESET_TEXT)
        return recovered

    def test_combined_empty_filters_restore_real_public_card_via_dom_href(self):
        event = self._event()
        response = self._get(tab="key", region=RacingRegion.GERMANY,
                             grade="g1", when="finished", year="2025", q="不匹配")
        self.assertEqual(response.context["filters"]["region"], RacingRegion.GERMANY)
        self.assertEqual(response.context["filters"]["grade"], "g1")
        self.assertEqual(response.context["filters"]["when"], "finished")
        clear_links = [link for link in self._links(response) if link["text"] == "清除"]
        self.assertEqual(len(clear_links), 1)
        self.assertEqual(parse_qs(urlsplit(clear_links[0]["href"]).query), {
            "tab": ["key"], "region": [RacingRegion.GERMANY.value],
            "grade": ["g1"], "when": ["finished"],
        })
        self._recover(response, event)

    def test_name_only_empty_filter_recovers(self):
        event = self._event()
        self._recover(self._get(tab="all", q="不匹配"), event)

    def test_year_only_empty_filter_recovers(self):
        event = self._event()
        self._recover(self._get(tab="all", year="2025"), event)

    def test_region_only_empty_filter_recovers(self):
        event = self._event()
        response = self._get(tab="all", region=RacingRegion.GERMANY)
        self.assertEqual(response.context["filters"]["region"], RacingRegion.GERMANY)
        self.assertFalse(any(link["text"] == "清除" for link in self._links(response)))
        self._recover(response, event)

    def test_grade_only_empty_filter_recovers(self):
        event = self._event()
        response = self._get(tab="all", grade="g1")
        self.assertEqual(response.context["filters"]["grade"], "g1")
        self._recover(response, event)

    def test_finished_only_empty_filter_recovers_scheduled_card(self):
        event = self._event()
        response = self._get(tab="all", when="finished")
        self.assertEqual(response.context["filters"]["when"], "finished")
        self._recover(response, event)

    def test_upcoming_only_empty_filter_recovers_finished_card_without_winner(self):
        event = self._event(status=RaceEventStatus.FINISHED)
        recovered = self._recover(self._get(tab="all", when="upcoming"), event)
        self.assertNotContains(recovered, "冠军")

    def test_default_key_empty_filter_recovers_non_key_card(self):
        event = self._event()
        response = self._get()
        self.assertEqual(response.context["filters"]["tab"], "key")
        self._recover(response, event)

    def test_undated_public_event_restores_existing_cross_period_fallback(self):
        event = self._event(local_date=None)
        self.assertIsNone(public_time(event).day, "前件：赛事没有有效公开日期")
        recovered = self._recover(self._get(tab="all", q="不匹配"), event)
        self.assertIsNone(recovered.context["default_anchor_date"])
        self.assertEqual(recovered.context["date_axis"], [])
        self.assertIsNone(recovered.context["groups"][0]["date"])
        self.assertContains(recovered, "北京时间待定")
        self.assertNotContains(recovered, "00:00")

    def test_exclusive_valid_return_nav_restores_empty_filters_before_reset(self):
        event = self._event()
        filters = {"tab": "all", "region": RacingRegion.GERMANY.value, "q": "不匹配"}
        token = _public_nav_token("races", filters)
        self.assertTrue(token, "前件失败：真实 producer 必须生成 token")
        self.assertEqual(_public_read_nav(token, {"races"}), ("races", filters))
        response = self._get(return_nav=token)
        self.assertEqual(dict(response.wsgi_request.GET.items()), filters)
        for key, value in filters.items():
            self.assertEqual(response.context["filters"][key], value)
        self._recover(response, event)

    def test_valid_future_cursor_past_last_row_recovers_without_old_cursor(self):
        event = self._event()
        filters = {"tab": "all", "year": str(TODAY.year)}
        cursor = encode_race_calendar_cursor(event, filters=filters)
        decoded = decode_race_calendar_cursor(cursor, filters=filters)
        self.assertIsNotNone(decoded, "前件失败：真实 cursor 必须可解码")
        self.assertEqual(decoded.event_id, event.pk)
        response = self._get(**filters, cursor=cursor, direction="future")
        self.assertEqual(response.context["filters"]["cursor"], cursor)
        self.assertEqual(response.context["filters"]["direction"], "future")
        self._recover(response, event)

    def test_default_all_empty_has_original_copy_without_useless_reset(self):
        response = self._get(tab="all")
        self._empty(response)
        self.assertContains(response, OLD_EMPTY_TEXT)
        self.assertNotContains(response, RESET_TEXT)
        self.assertNotContains(response, RESET_HINT)

    def test_hidden_and_canonical_duplicates_do_not_become_public_after_reset(self):
        canonical = self._event(visibility_status=RaceEventVisibility.HIDDEN)
        duplicate = self._event()
        approver = get_user_model().objects.create_user(username="d003-synthetic-approver")
        RaceEventProductCanonicalLink.objects.create(
            duplicate_event=duplicate, canonical_event=canonical,
            identity_sha256="a" * 64, manifest_sha256="b" * 64,
            approved_by=approver, approved_at=NOW, is_active=True,
        )
        default = self._get(tab="all")
        self._empty(default)
        self.assertContains(default, OLD_EMPTY_TEXT)
        self.assertNotContains(default, RESET_TEXT)
        self.assertNotContains(default, canonical.chinese_name)
        self.assertNotContains(default, duplicate.chinese_name)
        response = self._get(tab="all", q="不匹配")
        href = self._reset_href(response)
        recovered = self.client.get(href)
        self.assertEqual(recovered.status_code, 200)
        self._empty(recovered)
        self.assertContains(recovered, OLD_EMPTY_TEXT)
        for event in (canonical, duplicate):
            self.assertNotContains(recovered, event.chinese_name)
            self.assertNotContains(recovered, event.public_path)
        self.assertNotContains(recovered, RESET_TEXT)

    def test_matching_card_preserves_detail_return_navigation_without_empty_ui(self):
        event = self._event()
        response = self._get(tab="all", q=event.chinese_name)
        self.assertEqual(self._ids(response), [event.pk])
        cards = [link for link in self._links(response) if "cal-card" in link["class"]]
        self.assertEqual(len(cards), 1)
        token = parse_qs(urlsplit(cards[0]["href"]).query)["return_nav"][0]
        kind, filters = _public_read_nav(token, {"races"})
        self.assertEqual(kind, "races")
        self.assertEqual(filters["q"], event.chinese_name)
        detail = self.client.get(cards[0]["href"])
        self.assertEqual(detail.status_code, 200)
        returns = [link for link in self._links(detail)
                   if urlsplit(link["href"]).path == self.url
                   and "return_nav" in parse_qs(urlsplit(link["href"]).query)]
        self.assertEqual(len(returns), 1)
        returned = self.client.get(returns[0]["href"])
        self.assertEqual(returned.status_code, 200)
        self.assertEqual(returned.context["filters"]["q"], event.chinese_name)
        self.assertEqual(self._ids(returned), [event.pk])
        self.assertNotContains(response, EMPTY_TEXT)
        self.assertNotContains(response, RESET_TEXT)

    def test_unknown_query_redirect_is_checked_separately_from_empty_page(self):
        event = self._event()
        initial = self.client.get(self.url, {"tab": "all", "q": "不匹配", "unknown": "x"})
        self.assertEqual(initial.status_code, 301)
        target = urlsplit(initial["Location"])
        self.assertEqual(target.path, self.url)
        self.assertEqual(parse_qs(target.query), {"tab": ["all"], "q": ["不匹配"]})
        final = self.client.get(initial["Location"])
        self.assertEqual(final.status_code, 200)
        self.assertNotIn("unknown", final.wsgi_request.GET)
        self._recover(final, event)

    def test_invalid_filters_and_cursor_use_normalized_all_empty_contract(self):
        response = self._get(tab="all", region="invalid", grade="invalid", when="invalid",
                             cursor="invalid", direction="future")
        self._empty(response)
        for key in ("region", "grade", "when", "cursor", "direction"):
            self.assertEqual(response.context["filters"][key], "")
        self.assertContains(response, OLD_EMPTY_TEXT)
        self.assertNotContains(response, RESET_TEXT)

    def test_search_text_is_escaped_and_cannot_control_recovery_href(self):
        event = self._event()
        query = '<script data-d003="x">𠮷</script>'
        response = self._get(tab="all", q=query)
        self.assertEqual(response.context["filters"]["q"], query)
        self.assertNotContains(response, query)
        self._recover(response, event)

    def test_date_only_and_display_flags_preserve_unknown_clock_after_reset(self):
        event = self._event(country_region=RacingRegion.GERMANY, timezone_name="Europe/Berlin")
        self.assertEqual(public_time(event).day, TODAY)
        self.assertIsNone(public_time(event).instant)
        for new in (False, True):
            for old in (False, True):
                with self.subTest(new=new, old=old), override_settings(
                    RACE_INFORMATION_NORMALIZED_DISPLAY_ENABLED=new,
                    RACE_FIELD_NORMALIZED_DISPLAY_ENABLED=old,
                ):
                    recovered = self._recover(self._get(tab="all", q="不匹配"), event)
                    self.assertEqual(recovered.context["groups"][0]["date"], TODAY)
                    self.assertContains(recovered, "北京时间待定")
                    self.assertNotContains(recovered, "00:00")
                    self.assertNotContains(recovered, "冠军")

    def test_reset_does_not_promote_unconfirmed_result_to_finished_filter_or_winner(self):
        event = self._event(status=RaceEventStatus.FINISHED)
        RaceEventResult.objects.create(event=event, finish_position=1,
                                       horse_name="合成未确认第一名", is_confirmed=False)
        recovered = self._recover(self._get(tab="all", when="finished"), event)
        self.assertNotContains(recovered, "合成未确认第一名")
        self.assertNotContains(recovered, "冠军")
