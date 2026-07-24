"""
Test race calendar responsive UI -- A (date display & status) & B (badge, title, shared components).

All tests target the current production templates & CSS as they exist in the worktree.
Expected REDs are documented in the test docstrings.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.test import TestCase, override_settings
from django.urls import reverse

from stable.models import (
    RaceEvent,
    RaceEventPriority,
    RaceEventStatus,
    RaceEventVisibility,
    RaceGrade,
    RacingRegion,
)

# ---------------------------------------------------------------------------
# Counter for unique slugs
# ---------------------------------------------------------------------------
_event_counter = 0
_FIXED_TODAY = date(2026, 7, 24)


def _make_event(*, local_date: date | None, normalized_grade: str = "",
                chinese_name: str = "测试赛事",
                priority: str = RaceEventPriority.P0,
                status: str = RaceEventStatus.SCHEDULED,
                **kw) -> RaceEvent:
    """Minimal publishable RaceEvent fixture with guaranteed unique slug."""
    global _event_counter
    _event_counter += 1
    date_part = local_date.isoformat() if local_date else "undated"
    slug = f"test-{date_part}-c{_event_counter}"
    return RaceEvent.objects.create(
        year=local_date.year if local_date else 2026,
        slug=slug,
        original_name="Test Race",
        chinese_name=chinese_name,
        country_region=RacingRegion.JAPAN,
        racecourse="阪神",
        grade_text=normalized_grade or "G1",
        normalized_grade=normalized_grade or "",
        surface="turf",
        local_date=local_date,
        priority=priority,
        status=status,
        visibility_status=RaceEventVisibility.PUBLISHED,
        **kw,
    )


def _css_path() -> Path:
    """Return absolute path to public.css (inside the stable app static dir)."""
    # Stable app static is at stable/static/stable/public.css
    base = Path(settings.BASE_DIR)  # server/
    return base / "stable" / "static" / "stable" / "public.css"


def _read_css() -> str:
    with open(_css_path(), encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# A: date display & status
# ---------------------------------------------------------------------------

@override_settings(TIME_ZONE="Asia/Shanghai")
class CalendarDateDisplayTests(TestCase):
    """A1-A11 -- date rendering, cross-year, today, focus, undated, links, query count,
    non-hardcoded."""

    def setUp(self):
        super().setUp()
        today_patcher = patch("stable.views.timezone.localdate", return_value=_FIXED_TODAY)
        today_patcher.start()
        self.addCleanup(today_patcher.stop)

    def _html(self, **params) -> str:
        resp = self.client.get(reverse("public-race-calendar"), data=params)
        return resp.content.decode("utf-8")

    @staticmethod
    def _date_axis_link_text(html: str, anchor_id: str) -> str:
        """Extract the visible &lt;b&gt; text from a date-axis link for `anchor_id`."""
        pattern = re.compile(
            r'<a\b[^>]*href="#' + re.escape(anchor_id) + r'"[^>]*>\s*<b>(.*?)</b>',
            re.DOTALL,
        )
        m = pattern.search(html)
        return m.group(1).strip() if m else ""

    @staticmethod
    def _agenda_day_text(html: str, anchor_id: str) -> dict[str, str]:
        """Extract visible .m / .d / .date-year text from the agenda-day `anchor_id`."""
        section_pattern = re.compile(
            r'<section\b[^>]*id="' + re.escape(anchor_id) + r'"[^>]*>(.*?)</section>',
            re.DOTALL,
        )
        sm = section_pattern.search(html)
        if not sm:
            return {}
        section_html = sm.group(1)
        result = {}
        for cls in ("date-year", "m", "d"):
            m_cls = re.search(
                r'<div\b[^>]*class="[^"]*\b' + cls + r'\b[^"]*"[^>]*>(.*?)</div>',
                section_html,
                re.DOTALL,
            )
            if m_cls:
                result[cls] = re.sub(r"<[^>]+>", "", m_cls.group(1)).strip()
        return result

    # ----------------------------------------------------------------
    # A1: same-month dates 7-24 / 7-28
    # ----------------------------------------------------------------
    def test_a1_same_month_renders_month_day(self):
        """A1 -- date-axis and agenda both show '7月24日' / '7月28日' in visible text."""
        _make_event(local_date=date(2026, 7, 24), chinese_name="A1-1")
        _make_event(local_date=date(2026, 7, 28), chinese_name="A1-2")
        html = self._html(tab="all")
        # Date axis: extract the &lt;b&gt; text, not aria-label
        self.assertIn("7月24日", self._date_axis_link_text(html, "race-date-2026-07-24"),
                      "A1 RED: date-axis b should contain 7月24日")
        self.assertIn("7月28日", self._date_axis_link_text(html, "race-date-2026-07-28"),
                      "A1 RED: date-axis b should contain 7月28日")
        # Agenda: extract visible .m and .d, not aria-label
        g24 = self._agenda_day_text(html, "race-date-2026-07-24")
        self.assertEqual(g24.get("m"), "7月", "A1 RED: agenda .m should be 7月")
        self.assertEqual(g24.get("d"), "24日", "A1 RED: agenda .d should be 24日")
        g28 = self._agenda_day_text(html, "race-date-2026-07-28")
        self.assertEqual(g28.get("m"), "7月", "A1 RED: agenda .m should be 7月")
        self.assertEqual(g28.get("d"), "28日", "A1 RED: agenda .d should be 28日")

    # ----------------------------------------------------------------
    # A2: month-cross 7-28 / 8-1
    # ----------------------------------------------------------------
    def test_a2_month_cross_renders_month_day(self):
        """A2 -- month changes in visible date-axis and agenda text."""
        _make_event(local_date=date(2026, 7, 28), chinese_name="A2-1")
        _make_event(local_date=date(2026, 8, 1), chinese_name="A2-2")
        html = self._html(tab="all")
        self.assertIn("7月28日", self._date_axis_link_text(html, "race-date-2026-07-28"),
                      "A2 RED: date-axis b should contain 7月28日")
        self.assertIn("8月1日", self._date_axis_link_text(html, "race-date-2026-08-01"),
                      "A2 RED: date-axis b should contain 8月1日")
        g_jul = self._agenda_day_text(html, "race-date-2026-07-28")
        self.assertEqual(g_jul.get("m"), "7月", "A2: agenda .m should be 7月")
        g_aug = self._agenda_day_text(html, "race-date-2026-08-01")
        self.assertEqual(g_aug.get("m"), "8月", "A2: agenda .m should be 8月")

    # ----------------------------------------------------------------
    # A3: cross-year 2026-12-31 / 2027-01-01
    # ----------------------------------------------------------------
    def test_a3_cross_year_both_years_shown(self):
        """A3 -- visible date-year + month-day on both sides of year boundary."""
        _make_event(local_date=date(2026, 12, 31), chinese_name="A3-1")
        _make_event(local_date=date(2027, 1, 1), chinese_name="A3-2")
        html = self._html(tab="all", q="A3")
        # Date axis: year is wrapped in span.date-year inside &lt;b&gt;
        dec_text = self._date_axis_link_text(html, "race-date-2026-12-31")
        self.assertIn("2026年", dec_text, "A3 RED: date-axis should show 2026年 for Dec 31")
        self.assertIn("12月31日", dec_text, "A3 RED: date-axis should show 12月31日 for Dec 31")
        jan_text = self._date_axis_link_text(html, "race-date-2027-01-01")
        self.assertIn("2027年", jan_text, "A3 RED: date-axis should show 2027年 for Jan 1")
        self.assertIn("1月1日", jan_text, "A3 RED: date-axis should show 1月1日 for Jan 1")
        # Agenda: visible .date-year + .m + .d
        g_dec = self._agenda_day_text(html, "race-date-2026-12-31")
        self.assertEqual(g_dec.get("date-year"), "2026年", "A3 RED: agenda .date-year for Dec 31")
        self.assertEqual(g_dec.get("m"), "12月", "A3: agenda .m for Dec 31")
        g_jan = self._agenda_day_text(html, "race-date-2027-01-01")
        self.assertEqual(g_jan.get("date-year"), "2027年", "A3 RED: agenda .date-year for Jan 1")
        self.assertEqual(g_jan.get("m"), "1月", "A3: agenda .m for Jan 1")

    # ----------------------------------------------------------------
    # A4: single-year -- year not repeated unnecessarily
    # ----------------------------------------------------------------
    def test_a4_single_year_no_unnecessary_year(self):
        """A4 -- when all events are in one year, month+day is clear without redundant year."""
        _make_event(local_date=date(2026, 7, 24), chinese_name="A4-1")
        _make_event(local_date=date(2026, 7, 28), chinese_name="A4-2")
        html = self._html(tab="all")
        # Visible date-axis text must show month+day
        self.assertIn("7月24日", self._date_axis_link_text(html, "race-date-2026-07-24"),
                      "A4: date-axis b should contain 7月24日")
        # Single-year: no .date-year in date-axis link
        axis_text = self._date_axis_link_text(html, "race-date-2026-07-24")
        self.assertNotIn("2026年", axis_text,
                         "A4: single-year should not repeat year in visible date text")
        # Agenda: no .date-year div in single-year view
        g24 = self._agenda_day_text(html, "race-date-2026-07-24")
        self.assertNotIn("date-year", g24,
                         "A4: agenda should not have .date-year in single-year view")

    # ----------------------------------------------------------------
    # A5: weekday -- correct Chinese weekday
    # ----------------------------------------------------------------
    def test_a5_weekday_correct(self):
        """A5 -- date axis shows correct Chinese weekday (e.g. 2026-07-24 is 星期五)."""
        _make_event(local_date=date(2026, 7, 24), chinese_name="A5-1")
        html = self._html(tab="all")
        # 2026-07-24 is a Friday (星期五)
        self.assertIn("五", html, "A5: weekday should contain 五 for Friday 2026-07-24")

    # ----------------------------------------------------------------
    # A6: today -- class, label, aria-current, timeline emphasis
    # ----------------------------------------------------------------
    def test_a6_today_has_correct_markup(self):
        """A6 -- today has .today class, '今天' label, aria-current='date', timeline emphasis."""
        today = _FIXED_TODAY
        _make_event(local_date=today, chinese_name="A6-today")
        html = self._html(tab="all")
        # CSS class today on date-axis link
        self.assertIn('class="today"', html,
                      "A6: date-axis link should have today class")
        # '今天' label
        self.assertIn("今天", html,
                      "A6: should show '今天' label")
        # aria-current="date"
        self.assertIn('aria-current="date"', html,
                      "A6 RED: today link should have aria-current='date' (currently missing)")
        # Agenda section has today class
        self.assertIn('<section class="agenda-day today', html,
                      "A6: agenda-day should have today class")

    # ----------------------------------------------------------------
    # A7: race dots & focus strip
    # ----------------------------------------------------------------
    def test_a7_race_dots_and_focus_strip(self):
        """A7 -- .race-dot count matches dated groups; focus strip shows G1 only."""
        _make_event(local_date=date(2026, 7, 24), chinese_name="A7-G1", normalized_grade=RaceGrade.G1)
        _make_event(local_date=date(2026, 7, 25), chinese_name="A7-G2", normalized_grade=RaceGrade.G2)
        _make_event(local_date=date(2026, 7, 26), chinese_name="A7-no-grade", normalized_grade="")
        html = self._html(tab="all")
        race_dots = re.findall(r'race-dot', html)
        # Dots should appear for each dated group (3 dates -> 3 dots)
        self.assertEqual(len(race_dots), 3,
                         "A7: should have 3 race-dot spans for 3 dated groups")
        # Focus strip shows G1 only (inside the current week)
        # Check the focus strip section specifically
        focus_start = html.find('class="focus-strip"')
        focus_end = html.find('</section>', focus_start) if focus_start > -1 else -1
        focus_html = html[focus_start:focus_end] if focus_start > -1 else ""
        self.assertIn("A7-G1", focus_html if focus_html else html,
                      "A7: G1 event should appear in focus strip")
        self.assertNotIn("A7-G2", focus_html if focus_html else html,
                         "A7: G2 should not appear in focus strip")

    # ----------------------------------------------------------------
    # A8: undated events
    # ----------------------------------------------------------------
    def test_a8_undated_shows_placeholder(self):
        """A8 -- undated event shows '日期待定' and no fake year-month-day."""
        _make_event(local_date=None, chinese_name="A8-undated")
        # Also create a dated event to trigger the calendar
        _make_event(local_date=date(2026, 7, 24), chinese_name="A8-dated")
        html = self._html(tab="all")
        self.assertIn("日期待定", html, "A8: undated should show '日期待定'")
        # No fake year-month-day for the undated entry
        self.assertNotIn("1970", html, "A8: should not show 1970 or other fake date")
        self.assertNotIn("01月01", html, "A8: should not show fake Jan 1")

    # ----------------------------------------------------------------
    # A9: URL params & filters
    # ----------------------------------------------------------------
    def test_a9_filter_urls_and_anchors(self):
        """A9 -- tab/region/grade/when/year/q/cursor params, anchor IDs, detail URLs survive."""
        _make_event(local_date=date(2026, 7, 24), chinese_name="A9-events")
        html = self._html(tab="all")
        # Anchor ID for the group
        self.assertIn('id="race-date-2026-07-24"', html, "A9: missing anchor id")
        # Detail link (public_path) -- slug varies by counter, check for calendar card href
        self.assertIn('/races/2026/test-2026-07-24-', html, "A9: missing race detail URL")
        # Region tabs present
        self.assertIn('region-tabs', html, "A9: region tabs should be present")
        # Year filter present
        self.assertIn('name="year"', html, "A9: year filter should be present")
        # Search input
        self.assertIn('name="q"', html, "A9: search input should be present")

        # Test region filter preserves URL
        html_jp = self._html(tab="all", region="japan")
        self.assertIn("日本", html_jp, "A9: Japan region tab should be present")

    # ----------------------------------------------------------------
    # A10: query count -- initial window does not exceed 40
    # ----------------------------------------------------------------
    def test_a10_query_count_within_limit(self):
        """A10 -- default window fetches <=40 events (RACE_CALENDAR_PAGE_SIZE)."""
        # Create 50 events across 5 days
        today = _FIXED_TODAY
        for i in range(50):
            _make_event(
                local_date=today + timedelta(days=i // 10),
                chinese_name=f"A10-{i}",
            )
        resp = self.client.get(reverse("public-race-calendar"), {"tab": "all"})
        html = resp.content.decode("utf-8")
        event_count = html.count('class="cal-card"')
        self.assertLessEqual(event_count, 40,
                             "A10: should not show more than 40 events in default window")

    # ----------------------------------------------------------------
    # A11: non-hardcoded -- 2031/2032 fixtures show their own year
    # ----------------------------------------------------------------
    def test_a11_non_hardcoded_fixture_year(self):
        """A11 -- cross-year 2031/2032 shows each event's real year, never 2026."""
        _make_event(local_date=date(2031, 12, 31), chinese_name="A11-2031")
        _make_event(local_date=date(2032, 1, 1), chinese_name="A11-2032")
        # Use search to bypass date window and show both years
        html = self._html(tab="all", q="A11")
        # Date axis: each link must show its own year + month-day
        dec_text = self._date_axis_link_text(html, "race-date-2031-12-31")
        self.assertIn("2031年", dec_text, "A11 RED: date-axis should show 2031年 for Dec 2031")
        self.assertIn("12月31日", dec_text, "A11 RED: date-axis should show 12月31日 for Dec 2031")
        jan_text = self._date_axis_link_text(html, "race-date-2032-01-01")
        self.assertIn("2032年", jan_text, "A11 RED: date-axis should show 2032年 for Jan 2032")
        self.assertIn("1月1日", jan_text, "A11 RED: date-axis should show 1月1日 for Jan 2032")
        # Agenda: visible .date-year per group
        g_dec = self._agenda_day_text(html, "race-date-2031-12-31")
        self.assertEqual(g_dec.get("date-year"), "2031年", "A11 RED: agenda .date-year for Dec 2031")
        g_jan = self._agenda_day_text(html, "race-date-2032-01-01")
        self.assertEqual(g_jan.get("date-year"), "2032年", "A11 RED: agenda .date-year for Jan 2032")
        # Neither date-axis visible text should contain 2026年 (hardcoded year)
        self.assertNotIn("2026年", dec_text, "A11: date-axis should not hardcode 2026年")
        self.assertNotIn("2026年", jan_text, "A11: date-axis should not hardcode 2026年")


# ---------------------------------------------------------------------------
# B: badges, titles & shared components
# ---------------------------------------------------------------------------

@override_settings(TIME_ZONE="Asia/Shanghai")
class CalendarBadgeComponentTests(TestCase):
    """B1-B10 -- grade-badge sizing, mobile overrides, grade classes, empty, long titles,
    multi-card, shared usage, desktop layout."""

    def setUp(self):
        super().setUp()
        today_patcher = patch("stable.views.timezone.localdate", return_value=_FIXED_TODAY)
        today_patcher.start()
        self.addCleanup(today_patcher.stop)

    def _html(self, **params) -> str:
        resp = self.client.get(reverse("public-race-calendar"), data=params)
        return resp.content.decode("utf-8")

    # ----------------------------------------------------------------
    # B1: shared sizing contract
    # ----------------------------------------------------------------
    def test_b1_grade_badge_has_explicit_42px_dimensions(self):
        """B1 -- .grade-badge has explicit width, min-width, max-width, flex-basis, height all 42px."""
        css = _read_css()
        # Locate the .grade-badge block
        m = re.search(r'\.grade-badge\s*\{([^}]+)\}', css)
        self.assertIsNotNone(m, "B1: .grade-badge CSS block not found")
        block = m.group(1)
        # Must have width: 42px
        self.assertIn("width: 42px", block,
                      "B1 RED: .grade-badge missing explicit width: 42px")
        # Must have min-width: 42px
        self.assertIn("min-width: 42px", block,
                      "B1 RED: .grade-badge missing explicit min-width: 42px")
        # Must have max-width: 42px
        self.assertIn("max-width: 42px", block,
                      "B1 RED: .grade-badge missing explicit max-width: 42px")
        # Must have flex-basis: 42px (flex shorthand `0 0 42px` satisfies this)
        self.assertTrue(
            "flex-basis: 42px" in block or "flex: 0 0 42px" in block,
            "B1 RED: .grade-badge missing flex-basis: 42px (has flex: 0 0 42px)")
        # Must have height: 42px
        self.assertIn("height: 42px", block,
                      "B1: .grade-badge has height: 42px")

    # ----------------------------------------------------------------
    # B2: mobile override removed
    # ----------------------------------------------------------------
    def test_b2_mobile_no_flex_auto_override(self):
        """B2 -- @media (max-width: 599px) does NOT set .cal-card .grade-badge { flex: 0 0 auto }."""
        css = _read_css()
        # Find the mobile media query block -- use a more permissive regex to get the full block
        m = re.search(r'@media\s*\(max-width:\s*599px\)\s*\{', css)
        self.assertIsNotNone(m, "B2: mobile media query not found")
        start = m.start()
        # Count braces to find end
        depth = 0
        i = start
        while i < len(css):
            if css[i] == '{':
                depth += 1
            elif css[i] == '}':
                depth -= 1
                if depth == 0:
                    break
            i += 1
        mobile_block = css[start:i + 1]
        # Check for the specific offending rule inside the mobile block
        inner = re.search(r'\.cal-card\s*\.grade-badge\s*\{([^}]+)\}', mobile_block)
        if inner:
            inner_block = inner.group(1)
            self.assertNotIn("flex: 0 0 auto", inner_block,
                             "B2 RED: mobile block still has .cal-card .grade-badge { flex: 0 0 auto }")
        # If no inner match, the override has already been removed -- which is correct

    # ----------------------------------------------------------------
    # B3: G1/G2/G3 badge classes
    # ----------------------------------------------------------------
    def test_b3_grade_classes_render_correctly(self):
        """B3 -- G1/G2/G3 events render with grade-badge g1/g2/g3 classes."""
        _make_event(local_date=date(2026, 7, 24), chinese_name="B3-G1", normalized_grade=RaceGrade.G1)
        _make_event(local_date=date(2026, 7, 25), chinese_name="B3-G2", normalized_grade=RaceGrade.G2)
        _make_event(local_date=date(2026, 7, 26), chinese_name="B3-G3", normalized_grade=RaceGrade.G3)
        html = self._html(tab="all")
        self.assertIn('grade-badge g1', html, "B3: G1 badge class missing")
        self.assertIn('grade-badge g2', html, "B3: G2 badge class missing")
        self.assertIn('grade-badge g3', html, "B3: G3 badge class missing")
        # Grade label text also present
        self.assertIn("G1", html, "B3: G1 label text missing")
        self.assertIn("G2", html, "B3: G2 label text missing")
        self.assertIn("G3", html, "B3: G3 label text missing")

    # ----------------------------------------------------------------
    # B4: JPN1 four-character grade
    # ----------------------------------------------------------------
    def test_b4_jpn1_four_char_label(self):
        """B4 -- JPN1 renders as 4-char label in HTML."""
        _make_event(local_date=date(2026, 7, 24), chinese_name="B4-JPN1", normalized_grade=RaceGrade.JPN1)
        html = self._html(tab="all")
        self.assertIn("JPN1", html, "B4: JPN1 label should appear in HTML")

    # ----------------------------------------------------------------
    # B5: g-other four-char unknown grade
    # ----------------------------------------------------------------
    def test_b5_g_other_css_rules_exist(self):
        """B5 -- .g-other has white-space: normal; overflow-wrap: anywhere."""
        css = _read_css()
        m = re.search(r'\.g-other\s*\{([^}]+)\}', css)
        self.assertIsNotNone(m,
                             "B5 RED: .g-other CSS rule not found (needs white-space: normal; overflow-wrap: anywhere)")
        block = m.group(1)
        self.assertIn("white-space: normal", block,
                      "B5 RED: .g-other missing white-space: normal")
        self.assertIn("overflow-wrap: anywhere", block,
                      "B5 RED: .g-other missing overflow-wrap: anywhere")

    # ----------------------------------------------------------------
    # B6: empty grade placeholder
    # ----------------------------------------------------------------
    def test_b6_empty_grade_placeholder(self):
        """B6 -- .grade-badge:empty::before shows a dash or placeholder."""
        css = _read_css()
        m = re.search(r'\.grade-badge:empty::before\s*\{([^}]+)\}', css)
        self.assertIsNotNone(m,
                             "B6 RED: .grade-badge:empty::before CSS rule not found (needs content placeholder)")
        block = m.group(1)
        # Should have content that shows a dash
        self.assertIn("content:", block, "B6: :empty::before should have content property")

    # ----------------------------------------------------------------
    # B7: long title overflow-wrap
    # ----------------------------------------------------------------
    def test_b7_cal_card_name_overflow_wrap(self):
        """B7 -- .cal-card-name has overflow-wrap: anywhere."""
        css = _read_css()
        m = re.search(r'\.cal-card-name\s*\{([^}]+)\}', css)
        self.assertIsNotNone(m, "B7: .cal-card-name CSS rule not found")
        block = m.group(1)
        self.assertIn("overflow-wrap: anywhere", block,
                      "B7 RED: .cal-card-name missing overflow-wrap: anywhere")

    # ----------------------------------------------------------------
    # B8: multi-card consistent sizing
    # ----------------------------------------------------------------
    def test_b8_multi_card_badge_consistency(self):
        """B8 -- multiple cards have consistent badge classes and sizing."""
        _make_event(local_date=date(2026, 7, 24), chinese_name="B8-G1", normalized_grade=RaceGrade.G1)
        _make_event(local_date=date(2026, 7, 24), chinese_name="B8-G2", normalized_grade=RaceGrade.G2)
        html = self._html(tab="all")
        # Both badges have grade-badge class
        badges = re.findall(r'<span class="grade-badge\s+g[12]">', html)
        self.assertEqual(len(badges), 2, "B8: should find 2 grade-badge spans for 2 events")

    # ----------------------------------------------------------------
    # B9: shared badge on other pages
    # ----------------------------------------------------------------
    def test_b9_shared_badge_sizing_global(self):
        """B9 -- grade-badge globally is 42x42 (shared component)."""
        css = _read_css()
        m = re.search(r'\.grade-badge\s*\{([^}]+)\}', css)
        self.assertIsNotNone(m, "B9: .grade-badge CSS rule not found")
        block = m.group(1)
        # Confirm .grade-badge doesn't have conflicting width values inside color variants
        self.assertIn("width: 42px", block,
                      "B9 RED: .grade-badge missing width: 42px (same as B1)")
        # Confirm g1/g2/g3 classes don't override width
        for variant in ("g1", "g2", "g3"):
            pattern = r'\.grade-badge\.' + variant + r'\s*\{[^}]+?width:'
            vm = re.search(pattern, css)
            self.assertIsNone(vm, f"B9: .grade-badge.{variant} should NOT override width")

    # ----------------------------------------------------------------
    # B10: desktop layout 1440px
    # ----------------------------------------------------------------
    def test_b10_desktop_layout_badge_size(self):
        """B10 -- at 1440px, the calendar card is horizontal, badge 42x42."""
        css = _read_css()
        # The default (non-media-query) .cal-card rule should be the desktop one
        m = re.search(r'\.cal-card\s*\{([^}]+)\}', css)
        self.assertIsNotNone(m, "B10: .cal-card CSS rule not found")
        block = m.group(1)
        # Desktop layout: flex row (default) with center alignment
        self.assertIn("align-items: center", block,
                      "B10: .cal-card should have align-items: center (horizontal desktop)")
        # No flex-wrap on desktop
        self.assertNotIn("flex-wrap: wrap", block,
                         "B10: desktop .cal-card should not have flex-wrap")
