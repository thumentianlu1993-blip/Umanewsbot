"""
统计和业务判断测试 —— 复现当前归一化缺失导致的统计错误。

测试用例编号对应 test_cases.md 第 6 节(49-57)：
  - "01" 不计冠军(当前), "10" 误计冠军(当前)
  - "02"/"03" 不计亚军/季军
  - SCR/NR/Withdrawn 的出赛计数不准确
  - 主胜鞍候选可能遗漏 "01" 完赛记录
  - _horse_record_position 对 "01" 返回原文而非 "1"

RED 预期：
  1. "01" finish_position + result_status≠WON → 断言 wins_count == 1 失败
     (因 startswith("1") 不匹配 "01")
  2. "10" finish_position + result_status≠WON → 断言 wins_count == 0 失败
     (因 startswith("1") 误配 "10")
  3. "02" → seconds_count == 1 失败
  4. "03" → thirds_count == 1 失败
  5. WITHDRAWN → starts_count == 0 失败 (只有 SCRATCHED 被排除)
  6. "_horse_record_position('01')" → "1" 断言失败 (返回 "-")
"""

from __future__ import annotations

from datetime import date

from django.test import TestCase

from stable.models import (
    HorseProfile,
    HorseProfileStatus,
    HorseRaceRecord,
    HorseRaceResultStatus,
    HorseRaceStartStatus,
    RacingRegion,
    TermEntry,
    TermType,
    SourceLanguage,
)
from stable.views import _horse_record_position, _public_horse_queryset

# major_win_records 是主胜鞍候选函数，当前只依赖 result_status
# 不依赖 normalized_finish_position，但写入路径没有规范化因此可能遗漏
from stable.services.horse_profiles import major_win_records


class _StatsTestBase(TestCase):
    """基类：创建一条公开马匹档案和一条履历记录。"""

    def _make_term(self) -> TermEntry:
        return TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language=SourceLanguage.ENGLISH,
            source_ja="Test Horse",
            target_zh="测试马",
        )

    def _make_profile(self, **overrides) -> HorseProfile:
        kwargs = dict(
            primary_term=self._make_term(),
            original_name="Test Horse",
            display_name_zh="测试马",
            racing_region=RacingRegion.HONG_KONG,
            review_status=HorseProfileStatus.PUBLISHED,
        )
        kwargs.update(overrides)
        return HorseProfile.objects.create(**kwargs)

    def _make_record(
        self,
        profile: HorseProfile,
        finish_position: str = "",
        result_status: str = HorseRaceResultStatus.PLACED,
        start_status: str = HorseRaceStartStatus.STARTED,
        **overrides,
    ) -> HorseRaceRecord:
        kwargs = dict(
            horse_profile=profile,
            race_name="Test Race",
            race_date=date(2024, 1, 1),
            source_name="test-source",
            source_url="https://example.com/test",
            finish_position=finish_position,
            result_status=result_status,
            start_status=start_status,
        )
        kwargs.update(overrides)
        return HorseRaceRecord.objects.create(**kwargs)


class TestWinsCount(_StatsTestBase):
    """测试用例 49, 52 —— 冠军计数误判。"""

    def test_01_should_count_as_one_win(self) -> None:
        """TestCase 49: "01" 完赛应计冠军，但 startswith('1') 不匹配 '01'。"""
        profile = self._make_profile()
        self._make_record(profile, finish_position="01")
        p = _public_horse_queryset().get(pk=profile.pk)
        # RED: 当前代码 startswith("1") 不命中 "01" → wins_count=0
        self.assertEqual(
            p.wins_count,
            1,
            '"01" finish_position 应计 1 次冠军，当前被 startswith("1") 遗漏',
        )

    def test_10_should_not_count_as_win(self) -> None:
        """TestCase 52: "10" 不应计冠军，但 startswith('1') 误配 '10'。"""
        profile = self._make_profile()
        self._make_record(profile, finish_position="10")
        p = _public_horse_queryset().get(pk=profile.pk)
        # RED: 当前代码 startswith("1") 命中 "10" → wins_count=1
        self.assertEqual(
            p.wins_count,
            0,
            '"10" finish_position 不应计冠军，当前被 startswith("1") 误计',
        )

    def test_1_without_won_status_counts_as_win(self) -> None:
        """TestCase 49: 数字 "1" 不带前导零应正常计冠军。"""
        profile = self._make_profile()
        self._make_record(profile, finish_position="1")
        p = _public_horse_queryset().get(pk=profile.pk)
        self.assertEqual(p.wins_count, 1)  # PASS —— 这个能正常工作


class TestSecondsCount(_StatsTestBase):
    """测试用例 50 —— 亚军计数。"""

    def test_02_should_count_as_one_second(self) -> None:
        """TestCase 50: "02" 应计亚军，但 startswith('2') 不匹配 '02'。"""
        profile = self._make_profile()
        self._make_record(profile, finish_position="02")
        p = _public_horse_queryset().get(pk=profile.pk)
        self.assertEqual(
            p.seconds_count,
            1,
            '"02" finish_position 应计 1 次亚军，当前被 startswith("2") 遗漏',
        )


class TestThirdsCount(_StatsTestBase):
    """测试用例 51 —— 季军计数。"""

    def test_03_should_count_as_one_third(self) -> None:
        """TestCase 51: "03" 应计季军，但 startswith('3') 不匹配 '03'。"""
        profile = self._make_profile()
        self._make_record(profile, finish_position="03")
        p = _public_horse_queryset().get(pk=profile.pk)
        self.assertEqual(
            p.thirds_count,
            1,
            '"03" finish_position 应计 1 次季军，当前被 startswith("3") 遗漏',
        )


class TestStartsCount(_StatsTestBase):
    """测试用例 53 —— 实际出赛计数。"""

    def test_scratched_not_counted_as_start(self) -> None:
        """SCRATCHED 被正确排除。"""
        profile = self._make_profile()
        self._make_record(profile, result_status=HorseRaceResultStatus.SCRATCHED)
        p = _public_horse_queryset().get(pk=profile.pk)
        self.assertEqual(p.starts_count, 0)  # PASS —— SCRATCHED 被排除

    def test_withdrawn_wrongly_counted_as_start(self) -> None:
        """TestCase 53: WITHDRAWN 只排除 SCRATCHED，不排除 WITHDRAWN。"""
        profile = self._make_profile()
        self._make_record(profile, result_status=HorseRaceResultStatus.WITHDRAWN)
        p = _public_horse_queryset().get(pk=profile.pk)
        # RED: starts_count 只排除 SCRATCHED，WITHDRAWN 被计入 1
        self.assertEqual(
            p.starts_count,
            0,
            "WITHDRAWN 记录不应计实际出赛，当前只排除 SCRATCHED",
        )

    def test_non_runner_statuses_not_excluded(self) -> None:
        """其他非出赛状态 (如 withdraw/unknown) 未被排除。"""
        profile = self._make_profile()
        self._make_record(profile, result_status=HorseRaceResultStatus.UNKNOWN)
        p = _public_horse_queryset().get(pk=profile.pk)
        # RED: UNKNOWN 未被排除
        self.assertEqual(
            p.starts_count,
            0,
            "result_status=UNKNOWN 记录不应计实际出赛，当前只排除 SCRATCHED",
        )


class TestHorseRecordPosition(_StatsTestBase):
    """测试用例 56 —— 马匹详情页名次显示。"""

    def test_01_returns_1(self) -> None:
        """_horse_record_position('01') 应返回 '1'。"""
        record = HorseRaceRecord(
            finish_position="01",
            result_status=HorseRaceResultStatus.PLACED,
        )
        pos = _horse_record_position(record)
        # RED: 当前 regex r"^\s*([123])(?:\D|$)" 不匹配 "01" → fallback 返回 "-"
        self.assertEqual(
            pos,
            "1",
            '_horse_record_position("01") 应返回 "1"，当前 regex 不匹配前导零',
        )

    def test_10_does_not_return_1(self) -> None:
        """_horse_record_position('10') 不应返回 '1'。"""
        record = HorseRaceRecord(
            finish_position="10",
            result_status=HorseRaceResultStatus.PLACED,
        )
        pos = _horse_record_position(record)
        self.assertNotEqual(pos, "1")  # PASS —— regex 拒绝 "10"


class TestMajorWinRecords(_StatsTestBase):
    """测试用例 56 —— 主胜鞍候选。"""

    def test_01_without_won_missing_from_major_win(self) -> None:
        """TestCase 56: 若 "01" finish_position 但 result_status≠WON，遗漏。"""
        profile = self._make_profile()
        record = self._make_record(
            profile,
            finish_position="01",
            result_status=HorseRaceResultStatus.UNPLACED,
        )
        mwr = list(major_win_records(profile))
        # RED: major_win_records 只 filter result_status=WON
        self.assertIn(
            record,
            mwr,
            "major_win_records 应通过 normalized_finish_position 包含 '01' "
            "完赛记录，当前只依赖 result_status=WON",
        )

    def test_10_with_won_included(self) -> None:
        """TestCase 56: "10" finish_position 若 result_status=WON 被误纳入。"""
        profile = self._make_profile()
        record = self._make_record(
            profile,
            finish_position="10",
            result_status=HorseRaceResultStatus.WON,
        )
        mwr = list(major_win_records(profile))
        # RED: major_win_records 只 filter result_status=WON，"10" 也进入
        self.assertNotIn(
            record,
            mwr,
            "major_win_records 不应包含 '10' 完赛记录（并非真正的冠军），"
            "当前只依赖 result_status=WON",
        )
