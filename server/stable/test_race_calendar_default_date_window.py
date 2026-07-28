"""
赛事日历默认日期窗口测试（fix-race-calendar-default-date-window）。

锁定目标合同（当前代码尚未实现，预期 RED 见各测试 docstring）：

- 默认模式（无合法 direction=past|future+cursor、无 year、无 q）以
  ``timezone.localdate(timezone=ZoneInfo("Asia/Shanghai"))`` 计算唯一 ``shanghai_today``，
  贯穿锚点、分组 is_today、状态标签与模板 today class / aria。
- 默认锚点：今天有赛事→今天；否则未来最早比赛日；否则最近历史比赛日。
- 窗口：锚点前最多 5 个实际比赛日 + 锚点 + 锚点后最多 5 个；一侧不足从另一侧
  按离锚点由近及远补足；升序、唯一、≤11、必含锚点；不补造无赛事自然日。
- 默认模式不再展示 local_date=None 的赛事；非法/不完整 cursor 安全回退默认模式。
- 锚点日期链接带 data-calendar-anchor 与 anchor class；今天锚点另有 today class 与
  aria-current="date"；回退锚点用 aria-current="true"。全页恰好一个锚点。
- 默认模式输出最小 scrollLeft 居中脚本；显式模式不输出。
- 40 卡上限下 11 个窗口日期每个至少保留 1 张同资格卡。
- 轻量默认页 ≤10 条 SQL。

时间控制：统一冻结 ``today=2026-07-27``（Asia/Shanghai），patch
``stable.views.timezone.localdate``（Mock 接受 kwargs，新代码带 timezone= 调用同样被拦截）。
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from stable.models import (
    RaceEvent,
    RaceEventPriority,
    RaceEventProductCanonicalLink,
    RaceEventStatus,
    RaceEventVisibility,
    RaceGrade,
    RacingRegion,
)

FIXED_TODAY = date(2026, 7, 27)
SHANGHAI_KEY = "Asia/Shanghai"
SHANGHAI = ZoneInfo(SHANGHAI_KEY)

_event_counter = 0


def _make_event(*, local_date: date | None, normalized_grade: str = "",
                chinese_name: str = "窗口测试赛事",
                priority: str = RaceEventPriority.P0,
                status: str = RaceEventStatus.SCHEDULED,
                country_region: str = RacingRegion.JAPAN,
                visibility_status: str = RaceEventVisibility.PUBLISHED,
                **kw) -> RaceEvent:
    """最小公开 RaceEvent fixture（唯一 slug 计数器），风格同 responsive_ui 测试。"""
    global _event_counter
    _event_counter += 1
    date_part = local_date.isoformat() if local_date else "undated"
    return RaceEvent.objects.create(
        year=local_date.year if local_date else 2026,
        slug=f"dw-{date_part}-c{_event_counter}",
        original_name="Window Test Race",
        chinese_name=chinese_name,
        country_region=country_region,
        racecourse="阪神",
        grade_text=normalized_grade or "G1",
        normalized_grade=normalized_grade or "",
        surface="turf",
        local_date=local_date,
        priority=priority,
        status=status,
        visibility_status=visibility_status,
        **kw,
    )


def _anchor_id(day: date) -> str:
    return f"race-date-{day.isoformat()}"


def _date_axis_html(html: str) -> str:
    m = re.search(
        r'<nav\b[^>]*class="[^"]*\bdate-axis\b[^"]*"[^>]*>(.*?)</nav>',
        html,
        re.DOTALL,
    )
    return m.group(1) if m else ""


def _axis_links(html: str) -> list[dict]:
    """按文档顺序解析日期栏链接：anchor_id / classes / aria_current / is_anchor。"""
    axis = _date_axis_html(html)
    links = []
    for tag_match in re.finditer(r"<a\b[^>]*>", axis):
        tag = tag_match.group(0)
        href = re.search(r'href="#(race-date-[^"]+)"', tag)
        if not href:
            continue
        cls = re.search(r'class="([^"]*)"', tag)
        aria = re.search(r'aria-current="([^"]*)"', tag)
        links.append({
            "anchor_id": href.group(1),
            "classes": cls.group(1).split() if cls else [],
            "aria_current": aria.group(1) if aria else None,
            "is_anchor": "data-calendar-anchor" in tag,
            "tag": tag,
        })
    return links


def _axis_ids(html: str) -> list[str]:
    return [link["anchor_id"] for link in _axis_links(html)]


def _axis_link_text(html: str, anchor_id: str) -> str:
    pattern = re.compile(
        r'<a\b[^>]*href="#' + re.escape(anchor_id) + r'"[^>]*>\s*<b>(.*?)</b>',
        re.DOTALL,
    )
    m = pattern.search(html)
    return re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else ""


def _agenda_section(html: str, anchor_id: str) -> str:
    m = re.search(
        r'<section\b[^>]*id="' + re.escape(anchor_id) + r'"[^>]*>(.*?)</section>',
        html,
        re.DOTALL,
    )
    return m.group(1) if m else ""


def _script_blocks(html: str) -> list[str]:
    return re.findall(r"<script\b[^>]*>(.*?)</script>", html, re.DOTALL | re.IGNORECASE)


@override_settings(TIME_ZONE="Asia/Shanghai")
class DefaultRaceDateWindowTests(TestCase):
    """view 级合同测试；冻结 today=2026-07-27。"""

    def setUp(self):
        super().setUp()
        patcher = patch("stable.views.timezone.localdate", return_value=FIXED_TODAY)
        self.localdate_mock = patcher.start()
        self.addCleanup(patcher.stop)

    def _get(self, **params):
        return self.client.get(reverse("public-race-calendar"), data=params)

    def _html(self, **params) -> str:
        resp = self._get(**params)
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode("utf-8")

    def _make_days(self, days, *, prefix="D", **kw):
        for day in days:
            _make_event(local_date=day, chinese_name=f"{prefix}-{day.isoformat()}", **kw)

    def _assert_single_anchor(self, html, day, *, aria_current, expect_today_class):
        links = _axis_links(html)
        anchors = [link for link in links if link["is_anchor"]]
        self.assertEqual(
            self._date_axis_anchor_attr_count(html), 1,
            "日期栏应恰好一个 data-calendar-anchor",
        )
        self.assertEqual(len(anchors), 1, "日期栏应恰好一个锚点链接")
        anchor = anchors[0]
        self.assertEqual(anchor["anchor_id"], _anchor_id(day))
        self.assertIn("anchor", anchor["classes"], "锚点链接应带 anchor class")
        self.assertEqual(anchor["aria_current"], aria_current)
        if expect_today_class:
            self.assertIn("today", anchor["classes"])
        else:
            self.assertNotIn("today", anchor["classes"])
        return anchor

    @staticmethod
    def _date_axis_anchor_attr_count(html) -> int:
        return _date_axis_html(html).count("data-calendar-anchor")

    def _assert_each_axis_date_has_card(self, html):
        for link in _axis_links(html):
            section = _agenda_section(html, link["anchor_id"])
            self.assertTrue(section, f"缺少 agenda 分组 {link['anchor_id']}")
            self.assertIn('class="cal-card"', section,
                          f"{link['anchor_id']} 应至少保留一张卡")

    # ------------------------------------------------------------------
    # RED-1：默认窗口 = 锚点前后各 5 个实际比赛日，不按自然日裁剪
    # ------------------------------------------------------------------
    def test_red1_default_window_is_11_actual_race_days(self):
        """RED-1：today±30 自然日外的合法比赛日也必须进入默认窗口。"""
        before = [date(2026, 7, 25), date(2026, 7, 22), date(2026, 7, 18),
                  date(2026, 6, 30), date(2026, 5, 10)]  # 05-10 距今 >30 自然日
        after = [date(2026, 7, 29), date(2026, 8, 2), date(2026, 8, 15),
                 date(2026, 9, 5), date(2026, 10, 1)]  # 10-01 距今 >30 自然日
        days = sorted(before + [FIXED_TODAY] + after)
        self._make_days(days, prefix="RED1")
        html = self._html(tab="all")
        self.assertEqual(
            _axis_ids(html),
            [_anchor_id(day) for day in days],
            "RED：当前实现按 today±30 自然日裁剪，会丢弃 2026-05-10 与 2026-10-01",
        )

    # ------------------------------------------------------------------
    # RED-2：今天无赛事、最近未来比赛日 >30 天，仍锚定未来比赛日
    # ------------------------------------------------------------------
    def test_red2_future_anchor_beyond_30_natural_days(self):
        """RED-2：当前实现返回空窗口；目标应锚定 2026-09-15。"""
        self._make_days([date(2026, 9, 15), date(2026, 9, 20)], prefix="RED2")
        html = self._html(tab="all")
        self.assertIn(
            _anchor_id(date(2026, 9, 15)), _axis_ids(html),
            "RED：当前实现 today±30 内无赛事时返回空窗口",
        )
        self._assert_single_anchor(
            html, date(2026, 9, 15), aria_current="true", expect_today_class=False,
        )

    # ------------------------------------------------------------------
    # 锚点标记
    # ------------------------------------------------------------------
    def test_today_anchor_has_today_class_and_aria_date(self):
        """今天为锚点：today+anchor class、aria-current=date、全页唯一锚点。"""
        self._make_days([FIXED_TODAY, date(2026, 7, 30)], prefix="TA")
        html = self._html(tab="all")
        self._assert_single_anchor(
            html, FIXED_TODAY, aria_current="date", expect_today_class=True,
        )

    def test_future_anchor_has_aria_true_without_today_class(self):
        """未来锚点：data-calendar-anchor + aria-current=true，无 today class。"""
        self._make_days([date(2026, 8, 10), date(2026, 8, 12)], prefix="FA")
        html = self._html(tab="all")
        self._assert_single_anchor(
            html, date(2026, 8, 10), aria_current="true", expect_today_class=False,
        )

    def test_past_fallback_anchor_has_aria_true_without_today_class(self):
        """无今天且无未来赛事：最近历史比赛日为锚点，aria-current=true。"""
        self._make_days([date(2026, 7, 10), date(2026, 7, 20), date(2026, 7, 22)],
                        prefix="PA")
        html = self._html(tab="all")
        self._assert_single_anchor(
            html, date(2026, 7, 22), aria_current="true", expect_today_class=False,
        )

    # ------------------------------------------------------------------
    # 空状态
    # ------------------------------------------------------------------
    def test_no_public_events_renders_existing_empty_state(self):
        resp = self._get(tab="all")
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode("utf-8")
        self.assertIn("暂无符合条件的赛事", html)
        self.assertEqual(_axis_links(html), [], "空状态不应渲染日期轴")

    # ------------------------------------------------------------------
    # 窗口补足
    # ------------------------------------------------------------------
    def test_before_shortfall_filled_from_after_side(self):
        """锚点前仅 2 个比赛日：从后侧按由近及远补足到 11。"""
        before = [date(2026, 7, 25), date(2026, 7, 26)]
        after = [date(2026, 7, 29), date(2026, 8, 1), date(2026, 8, 5),
                 date(2026, 8, 12), date(2026, 8, 20), date(2026, 9, 1),
                 date(2026, 9, 15), date(2026, 10, 5)]
        days = sorted(before + [FIXED_TODAY] + after)
        self._make_days(days, prefix="BF")
        html = self._html(tab="all")
        self.assertEqual(_axis_ids(html), [_anchor_id(day) for day in days])

    def test_after_shortfall_filled_from_before_side(self):
        """锚点后仅 2 个比赛日：从前侧按由近及远补足到 11。"""
        before = [date(2026, 5, 15), date(2026, 5, 30), date(2026, 6, 10),
                  date(2026, 6, 20), date(2026, 7, 5), date(2026, 7, 14),
                  date(2026, 7, 21), date(2026, 7, 25)]
        after = [date(2026, 7, 28), date(2026, 7, 30)]
        days = sorted(before + [FIXED_TODAY] + after)
        self._make_days(days, prefix="AF")
        html = self._html(tab="all")
        self.assertEqual(_axis_ids(html), [_anchor_id(day) for day in days])

    def test_total_race_days_below_limit_shows_only_actual_days(self):
        """总比赛日 <11：仅展示实际日期、升序、唯一。"""
        days = [date(2026, 7, 25), FIXED_TODAY, date(2026, 8, 3), date(2026, 8, 10)]
        self._make_days(days, prefix="LT")
        # 同一天再加一场，验证日期唯一
        _make_event(local_date=FIXED_TODAY, chinese_name="LT-今日加场")
        html = self._html(tab="all")
        self.assertEqual(_axis_ids(html), [_anchor_id(day) for day in days])

    # ------------------------------------------------------------------
    # 非连续 / 跨月 / 跨年
    # ------------------------------------------------------------------
    def test_non_consecutive_race_days_do_not_insert_synthetic_days(self):
        days = [FIXED_TODAY, date(2026, 8, 10)]
        self._make_days(days, prefix="NC")
        html = self._html(tab="all")
        self.assertEqual(_axis_ids(html), [_anchor_id(day) for day in days])

    def test_cross_month_axis_visible_and_ordered(self):
        days = [FIXED_TODAY, date(2026, 8, 3)]
        self._make_days(days, prefix="CM")
        html = self._html(tab="all")
        self.assertEqual(_axis_ids(html), [_anchor_id(day) for day in days])
        self.assertIn("7月27日", _axis_link_text(html, _anchor_id(FIXED_TODAY)))
        self.assertIn("8月3日", _axis_link_text(html, _anchor_id(date(2026, 8, 3))))

    def test_cross_year_axis_keeps_both_year_labels(self):
        """跨年窗口：2026-12 与 2027-01 顺序正确、两年标识都在。"""
        self.localdate_mock.return_value = date(2026, 12, 28)
        days = [date(2026, 12, 28), date(2027, 1, 4)]
        self._make_days(days, prefix="CY")
        html = self._html(tab="all")
        self.assertEqual(_axis_ids(html), [_anchor_id(day) for day in days])
        axis = _date_axis_html(html)
        self.assertIn("2026年", axis)
        self.assertIn("2027年", axis)

    # ------------------------------------------------------------------
    # 上海时区白盒
    # ------------------------------------------------------------------
    def test_shanghai_today_computed_once_with_explicit_timezone(self):
        """view 必须以 timezone=ZoneInfo('Asia/Shanghai') 调用 localdate；
        同一冻结日同时驱动锚点、is_today/today class 与 aria。"""
        self._make_days([FIXED_TODAY, date(2026, 7, 29)], prefix="TZ")
        html = self._html(tab="all")
        shanghai_calls = [
            call for call in self.localdate_mock.call_args_list
            if getattr(call.kwargs.get("timezone"), "key", None) == SHANGHAI_KEY
        ]
        self.assertTrue(
            shanghai_calls,
            "RED：view 应以 timezone=ZoneInfo('Asia/Shanghai') 调用 localdate "
            "计算唯一 shanghai_today（当前为无参调用）",
        )
        self._assert_single_anchor(
            html, FIXED_TODAY, aria_current="date", expect_today_class=True,
        )

    # ------------------------------------------------------------------
    # 显式模式回归
    # ------------------------------------------------------------------
    def test_explicit_past_cursor_not_overridden_by_default_anchor(self):
        days = [date(2026, 7, 10), date(2026, 7, 18), FIXED_TODAY, date(2026, 8, 5)]
        self._make_days(days, prefix="XP")
        html = self._html(tab="all", direction="past", cursor="2026-07-20")
        ids = _axis_ids(html)
        self.assertIn(_anchor_id(date(2026, 7, 10)), ids)
        self.assertIn(_anchor_id(date(2026, 7, 18)), ids)
        self.assertNotIn(_anchor_id(FIXED_TODAY), ids)
        self.assertFalse(any(link["is_anchor"] for link in _axis_links(html)))
        self.assertFalse(
            any("data-calendar-anchor" in script for script in _script_blocks(html)),
            "显式 cursor 模式不应输出自动定位脚本",
        )

    def test_explicit_future_cursor_not_overridden_by_default_anchor(self):
        days = [date(2026, 7, 10), FIXED_TODAY, date(2026, 8, 5)]
        self._make_days(days, prefix="XF")
        html = self._html(tab="all", direction="future", cursor="2026-07-27")
        ids = _axis_ids(html)
        self.assertEqual(ids, [_anchor_id(date(2026, 8, 5))])
        self.assertFalse(any(link["is_anchor"] for link in _axis_links(html)))
        self.assertFalse(
            any("data-calendar-anchor" in script for script in _script_blocks(html)),
        )

    def test_year_mode_keeps_cross_period_results(self):
        self._make_days([date(2026, 3, 15), date(2026, 11, 20)], prefix="YR")
        html = self._html(tab="all", year="2026")
        ids = _axis_ids(html)
        self.assertIn(_anchor_id(date(2026, 3, 15)), ids)
        self.assertIn(_anchor_id(date(2026, 11, 20)), ids)
        self.assertFalse(any(link["is_anchor"] for link in _axis_links(html)))
        self.assertFalse(
            any("data-calendar-anchor" in script for script in _script_blocks(html)),
        )

    def test_q_mode_finds_history_beyond_30_days(self):
        _make_event(local_date=date(2026, 3, 1), chinese_name="远古纪念赛")
        html = self._html(tab="all", q="远古纪念")
        self.assertIn(_anchor_id(date(2026, 3, 1)), _axis_ids(html))
        self.assertIn("远古纪念赛", html)
        self.assertFalse(any(link["is_anchor"] for link in _axis_links(html)))

    def test_q_and_year_modes_exclude_hidden_and_active_duplicate(self):
        _make_event(local_date=date(2026, 7, 20), chinese_name="排除测试公开赛")
        _make_event(local_date=date(2026, 7, 21), chinese_name="排除测试隐藏赛",
                    visibility_status=RaceEventVisibility.HIDDEN)
        duplicate = _make_event(local_date=date(2026, 7, 22), chinese_name="排除测试重复赛")
        _make_event(local_date=date(2026, 7, 22), chinese_name="排除测试正赛")
        canonical = RaceEvent.objects.get(chinese_name="排除测试正赛")
        approver = get_user_model().objects.create_user(
            username="dw-approver", password="pass",
        )
        RaceEventProductCanonicalLink.objects.create(
            duplicate_event=duplicate,
            canonical_event=canonical,
            identity_sha256="a" * 64,
            manifest_sha256="b" * 64,
            approved_by=approver,
            approved_at=timezone.now(),
            is_active=True,
        )
        for params in ({"tab": "all", "q": "排除测试"}, {"tab": "all", "year": "2026"}):
            html = self._html(**params)
            self.assertIn("排除测试公开赛", html)
            self.assertIn("排除测试正赛", html)
            self.assertNotIn("排除测试隐藏赛", html)
            self.assertNotIn("排除测试重复赛", html)

    # ------------------------------------------------------------------
    # 非法 / 不完整 cursor 回退默认模式
    # ------------------------------------------------------------------
    def test_unparseable_cursor_falls_back_to_default_window(self):
        """无法解析的 cursor：安全回退默认模式（当前落入 past 截全库分支）。"""
        days = [date(2026, 7, 25), FIXED_TODAY, date(2026, 8, 1)]
        self._make_days(days, prefix="IC")
        html = self._html(tab="all", direction="past", cursor="not-a-date")
        self.assertEqual(
            _axis_ids(html), [_anchor_id(day) for day in days],
            "RED：非法 cursor 应回退默认窗口",
        )
        self._assert_single_anchor(
            html, FIXED_TODAY, aria_current="date", expect_today_class=True,
        )

    def test_cursor_with_invalid_or_missing_direction_falls_back_to_default(self):
        """direction 非 past/future 或缺失：回退默认模式（当前无边界截取全库前 40）。"""
        days = [date(2026, 7, 25), FIXED_TODAY, date(2026, 8, 1)]
        self._make_days(days, prefix="ID")
        for params in (
            {"tab": "all", "cursor": "2026-07-26", "direction": "bogus"},
            {"tab": "all", "cursor": "2026-07-26"},
        ):
            html = self._html(**params)
            self.assertEqual(
                _axis_ids(html), [_anchor_id(day) for day in days],
                f"RED：不完整 cursor {params} 应回退默认窗口",
            )
            self._assert_single_anchor(
                html, FIXED_TODAY, aria_current="date", expect_today_class=True,
            )

    # ------------------------------------------------------------------
    # 筛选参与窗口
    # ------------------------------------------------------------------
    def test_region_filter_scopes_anchor_window_and_cards(self):
        _make_event(local_date=FIXED_TODAY, chinese_name="日本今日",
                    country_region=RacingRegion.JAPAN)
        _make_event(local_date=date(2026, 8, 9), chinese_name="香港未来一",
                    country_region=RacingRegion.HONG_KONG)
        _make_event(local_date=date(2026, 8, 11), chinese_name="香港未来二",
                    country_region=RacingRegion.HONG_KONG)
        html = self._html(tab="all", region=RacingRegion.HONG_KONG)
        self.assertEqual(
            _axis_ids(html),
            [_anchor_id(date(2026, 8, 9)), _anchor_id(date(2026, 8, 11))],
            "region 过滤后窗口只能来自该地区赛事",
        )
        self.assertNotIn("日本今日", html)
        self._assert_each_axis_date_has_card(html)
        self._assert_single_anchor(
            html, date(2026, 8, 9), aria_current="true", expect_today_class=False,
        )

    def test_grade_filter_scopes_window(self):
        _make_event(local_date=FIXED_TODAY, chinese_name="无级别今日", normalized_grade="")
        _make_event(local_date=date(2026, 8, 8), chinese_name="G1未来",
                    normalized_grade=RaceGrade.G1)
        html = self._html(tab="all", grade="g1")
        self.assertEqual(_axis_ids(html), [_anchor_id(date(2026, 8, 8))])
        self.assertNotIn("无级别今日", html)
        section = _agenda_section(html, _anchor_id(date(2026, 8, 8)))
        self.assertIn("G1未来", section)
        self._assert_single_anchor(
            html, date(2026, 8, 8), aria_current="true", expect_today_class=False,
        )

    def test_when_filter_scopes_window(self):
        _make_event(local_date=FIXED_TODAY, chinese_name="今天预定",
                    status=RaceEventStatus.SCHEDULED)
        _make_event(local_date=date(2026, 7, 20), chinese_name="历史完赛",
                    status=RaceEventStatus.FINISHED)
        html = self._html(tab="all", when="finished")
        self.assertEqual(_axis_ids(html), [_anchor_id(date(2026, 7, 20))])
        self.assertNotIn("今天预定", html)
        self._assert_single_anchor(
            html, date(2026, 7, 20), aria_current="true", expect_today_class=False,
        )

    def test_region_without_events_renders_empty_state(self):
        _make_event(local_date=FIXED_TODAY, chinese_name="日本赛事")
        resp = self._get(tab="all", region=RacingRegion.FRANCE)
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode("utf-8")
        self.assertIn("暂无符合条件的赛事", html)
        self.assertEqual(_axis_links(html), [])

    # ------------------------------------------------------------------
    # 公开资格
    # ------------------------------------------------------------------
    def test_non_public_events_do_not_create_race_days(self):
        """hidden / draft / active canonical duplicate 不能单独制造比赛日。"""
        _make_event(local_date=FIXED_TODAY, chinese_name="公开今日")
        _make_event(local_date=date(2026, 8, 1), chinese_name="隐藏赛",
                    visibility_status=RaceEventVisibility.HIDDEN)
        _make_event(local_date=date(2026, 8, 3), chinese_name="草稿赛",
                    visibility_status=RaceEventVisibility.DRAFT)
        duplicate = _make_event(local_date=date(2026, 8, 5), chinese_name="重复赛")
        canonical = _make_event(local_date=date(2026, 8, 5), chinese_name="正赛")
        approver = get_user_model().objects.create_user(
            username="dw-approver-2", password="pass",
        )
        RaceEventProductCanonicalLink.objects.create(
            duplicate_event=duplicate,
            canonical_event=canonical,
            identity_sha256="c" * 64,
            manifest_sha256="d" * 64,
            approved_by=approver,
            approved_at=timezone.now(),
            is_active=True,
        )
        html = self._html(tab="all")
        ids = _axis_ids(html)
        self.assertNotIn(_anchor_id(date(2026, 8, 1)), ids)
        self.assertNotIn(_anchor_id(date(2026, 8, 3)), ids)
        self.assertNotIn("隐藏赛", html)
        self.assertNotIn("草稿赛", html)
        self.assertNotIn("重复赛", html)

    def test_only_non_public_events_renders_empty_state(self):
        _make_event(local_date=date(2026, 8, 1), chinese_name="隐藏独赛",
                    visibility_status=RaceEventVisibility.HIDDEN)
        _make_event(local_date=date(2026, 8, 3), chinese_name="草稿独赛",
                    visibility_status=RaceEventVisibility.DRAFT)
        html = self._html(tab="all")
        self.assertIn("暂无符合条件的赛事", html)
        self.assertEqual(_axis_links(html), [])

    # ------------------------------------------------------------------
    # 日期待定
    # ------------------------------------------------------------------
    def test_default_mode_with_only_undated_events_renders_empty_state(self):
        """默认模式不再展示 local_date=None 赛事（当前会展示 → RED）。"""
        _make_event(local_date=None, chinese_name="待定独赛")
        html = self._html(tab="all")
        self.assertIn(
            "暂无符合条件的赛事", html,
            "RED：默认模式只有日期待定赛事时应为空状态",
        )
        self.assertEqual(_axis_links(html), [])

    def test_q_mode_still_shows_undated_events(self):
        """显式 q 模式保留日期待定展示（现状，GREEN 守护）。"""
        _make_event(local_date=None, chinese_name="待定纪念赛")
        html = self._html(tab="all", q="待定纪念")
        self.assertIn("待定纪念赛", html)
        self.assertIn("日期待定", html)

    # ------------------------------------------------------------------
    # 跨日不重用手口窗口
    # ------------------------------------------------------------------
    def test_window_recomputed_when_shanghai_day_changes(self):
        """同一 test 内两个不同冻结 today 得到不同默认窗口与 today 标记。"""
        days = [date(2026, 7, 20) + timedelta(days=offset) for offset in range(15)]
        self._make_days(days, prefix="XD")
        html_day1 = self._html(tab="all")
        ids_day1 = _axis_ids(html_day1)
        self.assertEqual(
            ids_day1,
            [_anchor_id(date(2026, 7, 22) + timedelta(days=offset)) for offset in range(11)],
            "RED：today=07-27 的默认窗口应为 07-22..08-01 共 11 个实际比赛日",
        )
        self.localdate_mock.return_value = date(2026, 7, 28)
        html_day2 = self._html(tab="all")
        ids_day2 = _axis_ids(html_day2)
        self.assertEqual(
            ids_day2,
            [_anchor_id(date(2026, 7, 23) + timedelta(days=offset)) for offset in range(11)],
            "RED：today=07-28 的默认窗口应为 07-23..08-02，不复用前一天窗口",
        )
        self.assertNotEqual(ids_day1, ids_day2)
        day1_anchor = [link for link in _axis_links(html_day1) if "today" in link["classes"]]
        day2_anchor = [link for link in _axis_links(html_day2) if "today" in link["classes"]]
        self.assertEqual([link["anchor_id"] for link in day1_anchor],
                         [_anchor_id(date(2026, 7, 27))])
        self.assertEqual([link["anchor_id"] for link in day2_anchor],
                         [_anchor_id(date(2026, 7, 28))])

    # ------------------------------------------------------------------
    # 高基数 40 卡
    # ------------------------------------------------------------------
    def test_high_cardinality_keeps_40_card_cap_and_every_window_date(self):
        """11 日合计 55 场：渲染 ≤40 卡、11 个日期每个至少 1 张、日期栏含全部 11 日。"""
        before = [date(2026, 7, 18), date(2026, 7, 20), date(2026, 7, 22),
                  date(2026, 7, 24), date(2026, 7, 26)]
        after = [date(2026, 7, 28), date(2026, 7, 30), date(2026, 8, 1),
                 date(2026, 8, 3), date(2026, 8, 5)]
        for day in before:
            for index in range(6):
                _make_event(local_date=day, chinese_name=f"HC-{day.isoformat()}-{index}")
        for index in range(5):
            _make_event(local_date=FIXED_TODAY, chinese_name=f"HC-today-{index}")
        for day in after:
            for index in range(3):
                _make_event(local_date=day, chinese_name=f"HC-{day.isoformat()}-{index}")
        html = self._html(tab="all")
        card_count = html.count('class="cal-card"')
        self.assertLessEqual(card_count, 40, "40 卡上限必须保留")
        expected_days = sorted(before + [FIXED_TODAY] + after)
        self.assertEqual(
            _axis_ids(html),
            [_anchor_id(day) for day in expected_days],
            "RED：当前实现按赛事对象截前 40 场，前段密集日期会吞掉后段日期",
        )
        self._assert_each_axis_date_has_card(html)

    # ------------------------------------------------------------------
    # 查询预算
    # ------------------------------------------------------------------
    def test_light_default_page_query_count_within_budget(self):
        """轻量默认页 ≤10 条 SQL（既有 ≤8 + 获批 2 条有界日期聚合）。"""
        days = [FIXED_TODAY + timedelta(days=offset) for offset in range(-3, 5)]
        self._make_days(days, prefix="QB")
        with CaptureQueriesContext(connection) as context:
            resp = self._get(tab="all")
        self.assertEqual(resp.status_code, 200)
        self.assertLessEqual(
            len(context), 10,
            f"轻量默认页 SQL 不应超过 10 条，实际 {len(context)}",
        )

    # ------------------------------------------------------------------
    # 自动定位脚本
    # ------------------------------------------------------------------
    def test_default_mode_emits_anchor_centering_script(self):
        """默认模式输出最小脚本：只设置 .date-axis scrollLeft 居中锚点。"""
        _make_event(local_date=FIXED_TODAY, chinese_name="脚本锚点赛")
        html = self._html(tab="all")
        scripts = _script_blocks(html)
        centering = [
            script for script in scripts
            if "scrollLeft" in script and "data-calendar-anchor" in script
        ]
        self.assertTrue(
            centering,
            "RED：默认模式应输出引用 data-calendar-anchor 的 scrollLeft 居中脚本",
        )
        for script in centering:
            self.assertNotIn("scrollIntoView", script,
                             "居中脚本不得使用 scrollIntoView")
        self.assertFalse(
            any("scrollIntoView" in script for script in scripts),
            "页面不得使用 scrollIntoView（避免纵向跳动）",
        )

    def test_explicit_modes_emit_no_anchor_script(self):
        """显式 cursor/year/q 模式不输出自动定位脚本（GREEN 守护）。"""
        _make_event(local_date=date(2026, 7, 20), chinese_name="脚本历史赛")
        _make_event(local_date=date(2026, 8, 10), chinese_name="脚本未来赛")
        for params in (
            {"tab": "all", "direction": "past", "cursor": "2026-07-27"},
            {"tab": "all", "direction": "future", "cursor": "2026-07-27"},
            {"tab": "all", "year": "2026"},
            {"tab": "all", "q": "脚本"},
        ):
            html = self._html(**params)
            self.assertFalse(
                any("data-calendar-anchor" in script for script in _script_blocks(html)),
                f"显式模式 {params} 不应输出锚点定位脚本",
            )


class SelectBalancedRaceDatesTests(SimpleTestCase):
    """纯函数 select_balanced_race_dates 单测。

    服务模块 stable.services.race_calendar 尚未实现——import 写在方法体内，
    RED 阶段的 ModuleNotFoundError 属于预期，不阻塞本模块其他测试收集。
    """

    def _call(self, before_desc, anchor, after_asc, **kwargs):
        from stable.services.race_calendar import select_balanced_race_dates
        return select_balanced_race_dates(before_desc, anchor, after_asc, **kwargs)

    def test_basic_five_plus_anchor_plus_five(self):
        anchor = date(2026, 7, 27)
        before_desc = [anchor - timedelta(days=offset) for offset in range(1, 7)]
        after_asc = [anchor + timedelta(days=offset) for offset in range(1, 7)]
        result = self._call(before_desc, anchor, after_asc)
        self.assertEqual(
            result,
            [anchor - timedelta(days=offset) for offset in range(5, 0, -1)]
            + [anchor]
            + [anchor + timedelta(days=offset) for offset in range(1, 6)],
        )

    def test_before_shortfall_filled_from_after(self):
        anchor = date(2026, 7, 27)
        before_desc = [date(2026, 7, 26), date(2026, 7, 25)]
        after_asc = [date(2026, 7, 29), date(2026, 8, 1), date(2026, 8, 5),
                     date(2026, 8, 12), date(2026, 8, 20), date(2026, 9, 1),
                     date(2026, 9, 15), date(2026, 10, 5)]
        result = self._call(before_desc, anchor, after_asc)
        self.assertEqual(len(result), 11)
        self.assertEqual(result, sorted([date(2026, 7, 25), date(2026, 7, 26), anchor] + after_asc))

    def test_after_shortfall_filled_from_before(self):
        anchor = date(2026, 7, 27)
        before_desc = [date(2026, 7, 25), date(2026, 7, 21), date(2026, 7, 14),
                       date(2026, 7, 5), date(2026, 6, 20), date(2026, 6, 10),
                       date(2026, 5, 30), date(2026, 5, 15)]
        after_asc = [date(2026, 7, 28), date(2026, 7, 30)]
        result = self._call(before_desc, anchor, after_asc)
        self.assertEqual(len(result), 11)
        self.assertEqual(result, sorted(before_desc + [anchor] + after_asc))

    def test_total_below_limit_returns_all(self):
        anchor = date(2026, 7, 27)
        before_desc = [date(2026, 7, 25), date(2026, 7, 20)]
        after_asc = [date(2026, 8, 3), date(2026, 8, 10), date(2026, 8, 15)]
        result = self._call(before_desc, anchor, after_asc)
        self.assertEqual(
            result,
            [date(2026, 7, 20), date(2026, 7, 25), anchor,
             date(2026, 8, 3), date(2026, 8, 10), date(2026, 8, 15)],
        )

    def test_non_consecutive_days_no_synthetic_dates(self):
        anchor = date(2026, 7, 27)
        before_desc = [date(2026, 7, 10), date(2026, 6, 1)]
        after_asc = [date(2026, 9, 5)]
        result = self._call(before_desc, anchor, after_asc)
        allowed = set(before_desc) | {anchor} | set(after_asc)
        self.assertTrue(set(result) <= allowed, "不得补造无赛事自然日")
        self.assertEqual(result, sorted(result))

    def test_cross_month_and_cross_year(self):
        anchor = date(2026, 12, 30)
        before_desc = [date(2026, 12, 28), date(2026, 11, 15)]
        after_asc = [date(2027, 1, 2), date(2027, 1, 10)]
        result = self._call(before_desc, anchor, after_asc)
        self.assertEqual(
            result,
            [date(2026, 11, 15), date(2026, 12, 28), anchor,
             date(2027, 1, 2), date(2027, 1, 10)],
        )

    def test_invariants_anchor_ascending_unique_bounded(self):
        anchor = date(2026, 7, 27)
        before_desc = [anchor - timedelta(days=offset) for offset in range(1, 12)]
        after_asc = [anchor + timedelta(days=offset) for offset in range(1, 12)]
        result = self._call(before_desc, anchor, after_asc)
        self.assertIn(anchor, result)
        self.assertEqual(result, sorted(result))
        self.assertEqual(len(result), len(set(result)))
        self.assertLessEqual(len(result), 11)
        self.assertEqual(len(result), 11)

    def test_side_size_and_limit_parameters(self):
        anchor = date(2026, 7, 27)
        before_desc = [anchor - timedelta(days=offset) for offset in range(1, 6)]
        after_asc = [anchor + timedelta(days=offset) for offset in range(1, 6)]
        result = self._call(before_desc, anchor, after_asc, side_size=2, limit=5)
        self.assertEqual(
            result,
            [date(2026, 7, 25), date(2026, 7, 26), anchor,
             date(2026, 7, 28), date(2026, 7, 29)],
        )
