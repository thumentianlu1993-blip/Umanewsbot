"""
写入路径与功能开关测试 —— 验证新未接入字段/未定义开关的缺失。

测试用例编号对应 test_cases.md 第 5 节(41-48) 和 第 6 节(48a-48c)：
  - CSV import 不产生规范化字段 (41)
  - upsert_race_record 不保存规范化字段 (45)
  - Admin form 不包含新字段 (47)
  - 功能开关未定义 (48a)
  - 共享 normalizer 未被写入路径调用 (41-46)

RED 预期：
  1. upsert_race_record 后 record.normalized_finish_position 为空 → exists/not-none
  2. CSV import 后的 RaceEvent 没有规范化字段
  3. settings 中没有 RACE_FIELD_NORMALIZED_DISPLAY_ENABLED
  4. settings 中没有 RACE_FIELD_NORMALIZED_STATS_ENABLED
  5. .env.example 中没有上述两个开关
  6. RaceEventForm/HorseRaceRecordForm 不包含新规范化字段
  7. normalizer service 未在写入路径模块中被 import
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

from django.conf import settings
from django.test import TestCase

from stable.forms import HorseRaceRecordForm, RaceEventForm
from stable.models import (
    HorseProfile,
    HorseProfileStatus,
    HorseRaceRecord,
    HorseRaceResultStatus,
    HorseRaceStartStatus,
    RacingRegion,
    SourceLanguage,
    TermEntry,
    TermType,
)
from stable.services.horse_race_records import upsert_race_record


# ---------- normalize-race-and-career-fields design 中定义的新字段 ----------

NORMALIZED_HRR_FIELDS = {
    "normalized_finish_position",
    "normalized_result_status",
    "normalization_version",
    "normalization_input_sha256",
    "normalization_issues",
    "normalized_at",
    "distance_meters_normalized",
    "distance_precision",
    "normalized_surface",
    "normalized_race_type",
    "course_layout_text",
    "going_text",
    "race_term",
    "racecourse_term",
}

NORMALIZED_RACE_EVENT_FIELDS = {
    "racecourse_term",
    "normalization_version",
    "normalization_input_sha256",
    "normalization_issues",
    "normalized_at",
}


def _field_names(model_class) -> set[str]:
    return {f.name for f in model_class._meta.get_fields()}


# ====================== upsert 写入路径 ======================


class UpsertRaceRecordWritePathTest(TestCase):
    """TestCase 45: upsert_race_record 不保存规范化字段。"""

    def _make_term(self) -> TermEntry:
        return TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language=SourceLanguage.ENGLISH,
            source_ja="Test Horse",
            target_zh="测试马",
        )

    def setUp(self):
        self.profile = HorseProfile.objects.create(
            primary_term=self._make_term(),
            original_name="Test Horse",
            display_name_zh="测试马",
            racing_region=RacingRegion.HONG_KONG,
            review_status=HorseProfileStatus.PUBLISHED,
        )
        self.payload = {
            "race_name": "Happy Valley Race",
            "race_date": date(2024, 3, 20).isoformat(),
            "racecourse": "HV",
            "distance_text": "1200",
            "surface": "turf",
            "finish_position": "01",
            "source_name": "test-source",
            "source_url": "https://example.com/test",
        }

    def test_upsert_does_not_set_normalized_finish_position(self) -> None:
        """TestCase 45: upsert 后 normalized_finish_position 为空。"""
        result = upsert_race_record(self.profile, self.payload)
        record = result.record
        # RED: normalized_finish_position 字段不存在或为空
        normalized_finish = getattr(record, "normalized_finish_position", None)
        self.assertIsNotNone(
            normalized_finish,
            "upsert_race_record 后 normalized_finish_position 应为 1，"
            "但字段不存在或为 None（当前 upsert 未调用共享 normalizer）",
        )

    def test_upsert_does_not_set_normalized_result_status(self) -> None:
        """TestCase 45: upsert 后 normalized_result_status 为空。"""
        result = upsert_race_record(self.profile, self.payload)
        record = result.record
        normalized_status = getattr(record, "normalized_result_status", None)
        self.assertIsNotNone(
            normalized_status,
            "upsert_race_record 后 normalized_result_status 应为 finished，"
            "但字段不存在或为空（当前 upsert 未调用共享 normalizer）",
        )

    def test_upsert_does_not_set_normalization_version(self) -> None:
        """TestCase 45: upsert 后 normalization_version 为空。"""
        result = upsert_race_record(self.profile, self.payload)
        record = result.record
        version = getattr(record, "normalization_version", None)
        self.assertIsNotNone(
            version,
            "upsert_race_record 后 normalization_version 应为 "
            '"race-field-normalization.v1"，但字段不存在或为空',
        )

    def test_upsert_does_not_set_normalized_surface(self) -> None:
        """TestCase 45: upsert 后 normalized_surface 为空。"""
        result = upsert_race_record(self.profile, self.payload)
        record = result.record
        surface = getattr(record, "normalized_surface", None)
        self.assertIsNotNone(
            surface,
            "upsert 后 normalized_surface 应为 turf，但字段不存在或为空",
        )


# ====================== CSV import 写入路径 ======================


class CsvImportRaceEventWritePathTest(TestCase):
    """TestCase 41: CSV import 不产生规范化字段。"""

    def test_race_event_model_lacks_normalized_fields(self) -> None:
        """RaceEvent 模型没有设计中的规范化字段。"""
        actual_fields = _field_names(HorseRaceRecord)
        missing = NORMALIZED_HRR_FIELDS - actual_fields
        # RED: 规范化字段尚未在模型中定义
        self.assertFalse(
            missing,
            f"HorseRaceRecord 缺少以下目标规范化字段: {missing}",
        )

    def test_race_event_form_lacks_normalized_fields(self) -> None:
        """RaceEventForm 不含新规范化字段。"""
        form_fields = set(RaceEventForm().fields.keys())
        # RED: 规范化字段不在 form fields 中
        self.assertIn(
            "racecourse_term",
            form_fields,
            "RaceEventForm 应包含 racecourse_term 字段，但当前不存在",
        )


# ====================== Admin Form ======================


class AdminFormWritePathTest(TestCase):
    """TestCase 47: Admin form 不包含新规范化字段。"""

    def test_horse_race_record_form_lacks_normalized_fields(self) -> None:
        """HorseRaceRecordForm 不含规范化 finish/status 字段。"""
        form_fields = set(HorseRaceRecordForm().fields.keys())
        # RED: 规范化字段不在 form fields 中
        self.assertIn(
            "normalized_finish_position",
            form_fields,
            "HorseRaceRecordForm 应包含 normalized_finish_position 字段",
        )

    def test_horse_race_record_form_lacks_normalization_meta(self) -> None:
        """HorseRaceRecordForm 不含规范化元数据字段。"""
        form_fields = set(HorseRaceRecordForm().fields.keys())
        self.assertIn(
            "normalization_version",
            form_fields,
            "HorseRaceRecordForm 应包含 normalization_version 字段",
        )


# ====================== 功能开关 ======================


class FeatureFlagSettingsTest(TestCase):
    """TestCase 48a: 功能开关未在 settings.py 定义。"""

    def test_display_flag_not_defined(self) -> None:
        """RACE_FIELD_NORMALIZED_DISPLAY_ENABLED 未定义。"""
        # RED: 设置不存在 → AttributeError 或 hasattr 返回 False
        self.assertTrue(
            hasattr(settings, "RACE_FIELD_NORMALIZED_DISPLAY_ENABLED"),
            "settings.RACE_FIELD_NORMALIZED_DISPLAY_ENABLED 应已定义（默认 false），"
            "但当前未在 settings.py 中设置",
        )

    def test_stats_flag_not_defined(self) -> None:
        """RACE_FIELD_NORMALIZED_STATS_ENABLED 未定义。"""
        self.assertTrue(
            hasattr(settings, "RACE_FIELD_NORMALIZED_STATS_ENABLED"),
            "settings.RACE_FIELD_NORMALIZED_STATS_ENABLED 应已定义（默认 false），"
            "但当前未在 settings.py 中设置",
        )

    def test_display_flag_not_in_env_example(self) -> None:
        """.env.example 不含 RACE_FIELD_NORMALIZED_DISPLAY_ENABLED。"""
        env_example = Path(settings.BASE_DIR).parent / ".env.example"
        content = env_example.read_text(encoding="utf-8")
        self.assertIn(
            "RACE_FIELD_NORMALIZED_DISPLAY_ENABLED",
            content,
            ".env.example 中应包含 RACE_FIELD_NORMALIZED_DISPLAY_ENABLED 开关说明",
        )

    def test_stats_flag_not_in_env_example(self) -> None:
        """.env.example 不含 RACE_FIELD_NORMALIZED_STATS_ENABLED。"""
        env_example = Path(settings.BASE_DIR).parent / ".env.example"
        content = env_example.read_text(encoding="utf-8")
        self.assertIn(
            "RACE_FIELD_NORMALIZED_STATS_ENABLED",
            content,
            ".env.example 中应包含 RACE_FIELD_NORMALIZED_STATS_ENABLED 开关说明",
        )


# ====================== 共享 normalizer 未接入写入路径 ======================


class NormalizerNotIntegratedTest(TestCase):
    """共享正常化 service 未被写入路径调用。"""

    def test_normalizer_not_imported_by_upsert_module(self) -> None:
        """horse_race_records.py 未 import race_field_normalization。"""
        # RED: normalizer 模块未被写入路径导入
        self.assertIn(
            "stable.services.race_field_normalization",
            sys.modules,
            "race_field_normalization 应已被写入路径导入和调用，"
            "但当前未在任何写入路径模块中 import",
        )

    def test_normalizer_not_imported_by_race_events_service(self) -> None:
        """race_events.py 未 import race_field_normalization。"""
        self.assertIn(
            "stable.services.race_field_normalization",
            sys.modules,
            "race_field_normalization 应已被 race_events.py 导入（candidate apply 路径），"
            "但当前未 import",
        )

    def test_p0_production_apply_not_using_normalized_fields(self) -> None:
        """P0 candidate apply 不保存规范化字段。"""
        # 读取 p0_horse_production_apply.py 源码；不会真的执行 P0 apply
        apply_path = (
            Path(settings.BASE_DIR)
            / "stable"
            / "services"
            / "p0_horse_production_apply.py"
        )
        source = apply_path.read_text(encoding="utf-8")
        # RED: P0 apply 需要处理并保存规范化字段，但源码没有相关逻辑
        self.assertIn(
            "normalized_finish_position",
            source,
            "p0_horse_production_apply.py 应包含 normalized_finish_position 保存逻辑",
        )
