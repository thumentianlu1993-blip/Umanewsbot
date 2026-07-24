"""
RED tests for the race & career field normalization schema.

Each test attempts to *use* a target feature (field, enum, model, migration)
that has not been implemented yet.  The test therefore fails with a clear
RED signal -- FieldDoesNotExist, ImportError, LookupError, or file-not-found.
When the implementation is added, these tests will turn GREEN.

禁止 catch 预期异常 -- 让异常自然传播, 产生真实的 RED 输出.
"""

import importlib
import os
import sys
from pathlib import Path

from django.core.exceptions import FieldDoesNotExist
from django.test import TestCase

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app.settings")

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


# ===================================================================
# Enums -- 尝试导入尚不存在的枚举类, 预期 ImportError
# ===================================================================

class TestNormalizationEnumsRED(TestCase):
    """尝试导入 5 个归一化枚举类, 预期 ImportError."""

    def test_normalized_race_result_status_enum_red(self):
        from stable.models import NormalizedRaceResultStatus
        self.assertIsNotNone(NormalizedRaceResultStatus)  # unreachable

    def test_distance_precision_enum_red(self):
        from stable.models import DistancePrecision
        self.assertIsNotNone(DistancePrecision)

    def test_normalized_surface_enum_red(self):
        from stable.models import NormalizedSurface
        self.assertIsNotNone(NormalizedSurface)

    def test_normalized_race_type_enum_red(self):
        from stable.models import NormalizedRaceType
        self.assertIsNotNone(NormalizedRaceType)

    def test_race_sex_restriction_enum_red(self):
        from stable.models import RaceSexRestriction
        self.assertIsNotNone(RaceSexRestriction)


# ===================================================================
# HorseRaceRecord -- 尝试访问尚不存在的规范字段
# ===================================================================

class TestHorseRaceRecordFieldsRED(TestCase):
    """尝试读取 HorseRaceRecord 上的新字段, 预期 FieldDoesNotExist."""

    def test_normalized_finish_position_red(self):
        from stable.models import HorseRaceRecord
        HorseRaceRecord._meta.get_field("normalized_finish_position")

    def test_normalized_result_status_red(self):
        from stable.models import HorseRaceRecord
        HorseRaceRecord._meta.get_field("normalized_result_status")

    def test_normalization_version_red(self):
        from stable.models import HorseRaceRecord
        HorseRaceRecord._meta.get_field("normalization_version")

    def test_normalization_input_sha256_red(self):
        from stable.models import HorseRaceRecord
        HorseRaceRecord._meta.get_field("normalization_input_sha256")

    def test_normalization_issues_red(self):
        from stable.models import HorseRaceRecord
        HorseRaceRecord._meta.get_field("normalization_issues")

    def test_normalized_at_red(self):
        from stable.models import HorseRaceRecord
        HorseRaceRecord._meta.get_field("normalized_at")

    def test_distance_meters_normalized_red(self):
        from stable.models import HorseRaceRecord
        HorseRaceRecord._meta.get_field("distance_meters_normalized")

    def test_distance_precision_red(self):
        from stable.models import HorseRaceRecord
        HorseRaceRecord._meta.get_field("distance_precision")

    def test_normalized_surface_red(self):
        from stable.models import HorseRaceRecord
        HorseRaceRecord._meta.get_field("normalized_surface")

    def test_normalized_race_type_red(self):
        from stable.models import HorseRaceRecord
        HorseRaceRecord._meta.get_field("normalized_race_type")

    def test_course_layout_text_red(self):
        from stable.models import HorseRaceRecord
        HorseRaceRecord._meta.get_field("course_layout_text")

    def test_going_text_red(self):
        from stable.models import HorseRaceRecord
        HorseRaceRecord._meta.get_field("going_text")

    def test_race_term_red(self):
        from stable.models import HorseRaceRecord
        HorseRaceRecord._meta.get_field("race_term")

    def test_racecourse_term_red(self):
        from stable.models import HorseRaceRecord
        HorseRaceRecord._meta.get_field("racecourse_term")

    def test_eligibility_text_on_hrr_red(self):
        from stable.models import HorseRaceRecord
        HorseRaceRecord._meta.get_field("eligibility_text")

    def test_minimum_age_red(self):
        from stable.models import HorseRaceRecord
        HorseRaceRecord._meta.get_field("minimum_age")

    def test_maximum_age_red(self):
        from stable.models import HorseRaceRecord
        HorseRaceRecord._meta.get_field("maximum_age")

    def test_age_open_ended_red(self):
        from stable.models import HorseRaceRecord
        HorseRaceRecord._meta.get_field("age_open_ended")

    def test_sex_restriction_on_hrr_red(self):
        from stable.models import HorseRaceRecord
        HorseRaceRecord._meta.get_field("sex_restriction")

    def test_eligibility_constraints_red(self):
        from stable.models import HorseRaceRecord
        HorseRaceRecord._meta.get_field("eligibility_constraints")


# ===================================================================
# RaceEvent -- 尝试访问尚不存在的规范字段
# ===================================================================

class TestRaceEventFieldsRED(TestCase):
    """尝试读取 RaceEvent 上的新字段, 预期 FieldDoesNotExist."""

    def test_distance_meters_normalized_red(self):
        from stable.models import RaceEvent
        RaceEvent._meta.get_field("distance_meters_normalized")

    def test_distance_precision_red(self):
        from stable.models import RaceEvent
        RaceEvent._meta.get_field("distance_precision")

    def test_normalized_surface_red(self):
        from stable.models import RaceEvent
        RaceEvent._meta.get_field("normalized_surface")

    def test_normalized_race_type_red(self):
        from stable.models import RaceEvent
        RaceEvent._meta.get_field("normalized_race_type")

    def test_course_layout_text_red(self):
        from stable.models import RaceEvent
        RaceEvent._meta.get_field("course_layout_text")

    def test_going_text_red(self):
        from stable.models import RaceEvent
        RaceEvent._meta.get_field("going_text")

    def test_racecourse_term_red(self):
        from stable.models import RaceEvent
        RaceEvent._meta.get_field("racecourse_term")

    def test_minimum_age_red(self):
        from stable.models import RaceEvent
        RaceEvent._meta.get_field("minimum_age")

    def test_maximum_age_red(self):
        from stable.models import RaceEvent
        RaceEvent._meta.get_field("maximum_age")

    def test_age_open_ended_red(self):
        from stable.models import RaceEvent
        RaceEvent._meta.get_field("age_open_ended")

    def test_sex_restriction_red(self):
        from stable.models import RaceEvent
        RaceEvent._meta.get_field("sex_restriction")

    def test_eligibility_constraints_red(self):
        from stable.models import RaceEvent
        RaceEvent._meta.get_field("eligibility_constraints")

    def test_normalization_version_red(self):
        from stable.models import RaceEvent
        RaceEvent._meta.get_field("normalization_version")

    def test_normalization_input_sha256_red(self):
        from stable.models import RaceEvent
        RaceEvent._meta.get_field("normalization_input_sha256")

    def test_normalization_issues_red(self):
        from stable.models import RaceEvent
        RaceEvent._meta.get_field("normalization_issues")

    def test_normalized_at_red(self):
        from stable.models import RaceEvent
        RaceEvent._meta.get_field("normalized_at")


# ===================================================================
# RaceFieldNormalizationRun / Receipt -- 尝试获取尚不存在的模型
# ===================================================================

class TestRaceFieldNormalizationModelsRED(TestCase):
    """尝试从 app registry 获取新模型, 预期 LookupError."""

    def test_race_field_normalization_run_model_red(self):
        from django.apps import apps
        apps.get_model("stable", "RaceFieldNormalizationRun")

    def test_race_field_normalization_receipt_model_red(self):
        from django.apps import apps
        apps.get_model("stable", "RaceFieldNormalizationReceipt")


# ===================================================================
# Migrations -- 尝试 import 尚不存在的 migration 模块
# ===================================================================

class TestMigrationsRED(TestCase):
    """尝试 import migration 0054/0055 模块, 预期 ModuleNotFoundError."""

    def test_migration_0054_red(self):
        importlib.import_module("stable.migrations.0054_race_field_normalization_schema")

    def test_migration_0055_red(self):
        importlib.import_module("stable.migrations.0055_race_field_normalization_indexes")
