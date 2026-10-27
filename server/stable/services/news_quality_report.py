"""P01 只读观测报告接口；独立分母和实际日志是显式输入。"""
from datetime import timedelta
from django.utils import timezone


def timeliness(*, source_time, time_verified, priority, published_at, now):
    return {"status": "unknown", "delay_seconds": None}


def build_report(*, start, end, independent_events=(), exposure_records=None, exposure_access=None, evidence=None):
    return {"window": {"full_168_hours": False}, "major": {"denominator": 0, "unknown": 0, "overdue": 0},
            "discovery": {"candidates": 0, "failed": 0}, "exposure": {"status": "unknown", "responses": 0},
            "hard_checks": {}, "status": "observation_incomplete"}
