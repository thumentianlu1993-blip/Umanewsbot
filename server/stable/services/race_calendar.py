"""赛事日历默认日期窗口服务（fix-race-calendar-default-date-window）。

提供两个可独立测试的层次：

1. ``select_balanced_race_dates``：纯函数，在锚点两侧平衡挑选实际比赛日，
   不访问时钟或数据库。
2. ``public_default_race_date_window``：在已含公开资格与筛选的 queryset 上
   发出恰好两条有界 distinct 日期聚合查询，确定锚点并调用纯函数得到最多
   11 个比赛日及每个所选日期的代表赛事 ID。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time
from typing import Any

from django.core import signing
from django.core.signing import BadSignature
from django.db.models import Min
from django.db.models import Q

RACE_DATE_WINDOW_SIDE_SIZE = 5
RACE_DATE_WINDOW_LIMIT = 11
RACE_CALENDAR_CURSOR_SALT = "stable.public-race-calendar.cursor.v1"
RACE_CALENDAR_CURSOR_VERSION = 1


@dataclass(frozen=True)
class DefaultRaceDateWindow:
    """默认模式选定的日期窗口；无公开比赛日时 anchor 为 None、列表为空。"""

    anchor: date | None
    dates: list[date] = field(default_factory=list)
    representative_ids: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class RaceCalendarCursor:
    """显式年份/搜索模式下的稳定游标。"""

    date_is_null: int
    local_date: date | None
    time_is_null: int
    local_start_time: time | None
    event_id: int


def race_calendar_filter_fingerprint(filters: dict[str, str]) -> dict[str, str]:
    """返回影响结果集合的规范化筛选条件。

    游标只绑定这些字段；cursor/direction 本身不是筛选条件。
    """

    return {
        key: str(filters.get(key, ""))
        for key in ("tab", "region", "year", "q", "grade", "when")
    }


def encode_race_calendar_cursor(event, *, filters: dict[str, str]) -> str:
    local_date = event.local_date
    local_start_time = event.local_start_time
    payload = {
        "v": RACE_CALENDAR_CURSOR_VERSION,
        "filters": race_calendar_filter_fingerprint(filters),
        "key": {
            "date_is_null": int(local_date is None),
            "local_date": local_date.isoformat() if local_date else None,
            "time_is_null": int(local_start_time is None),
            "local_start_time": (
                local_start_time.isoformat() if local_start_time else None
            ),
            "event_id": event.pk,
        },
    }
    return signing.dumps(payload, salt=RACE_CALENDAR_CURSOR_SALT)


def decode_race_calendar_cursor(
    value: str,
    *,
    filters: dict[str, str],
) -> RaceCalendarCursor | None:
    """校验版本、筛选指纹和复合位置；无效输入统一返回 ``None``。"""

    try:
        payload: Any = signing.loads(
            value,
            salt=RACE_CALENDAR_CURSOR_SALT,
        )
        if (
            not isinstance(payload, dict)
            or payload.get("v") != RACE_CALENDAR_CURSOR_VERSION
            or payload.get("filters") != race_calendar_filter_fingerprint(filters)
        ):
            return None
        key = payload["key"]
        local_date = (
            date.fromisoformat(key["local_date"])
            if key.get("local_date")
            else None
        )
        local_start_time = (
            time.fromisoformat(key["local_start_time"])
            if key.get("local_start_time")
            else None
        )
        cursor = RaceCalendarCursor(
            date_is_null=int(key["date_is_null"]),
            local_date=local_date,
            time_is_null=int(key["time_is_null"]),
            local_start_time=local_start_time,
            event_id=int(key["event_id"]),
        )
    except (BadSignature, KeyError, TypeError, ValueError):
        return None
    if cursor.date_is_null not in {0, 1} or cursor.time_is_null not in {0, 1}:
        return None
    if cursor.date_is_null != int(cursor.local_date is None):
        return None
    if cursor.time_is_null != int(cursor.local_start_time is None):
        return None
    if cursor.event_id <= 0:
        return None
    return cursor


def race_calendar_cursor_filter(
    cursor: RaceCalendarCursor,
    *,
    direction: str,
) -> Q:
    """构造与 ``date NULLS LAST, time NULLS LAST, id`` 一致的 keyset 边界。"""

    if direction not in {"future", "past"}:
        raise ValueError("direction must be future or past")
    after = direction == "future"
    condition = Q()

    if cursor.local_date is None:
        date_prefix = Q(local_date__isnull=True)
        if not after:
            condition |= Q(local_date__isnull=False)
    else:
        date_prefix = Q(local_date=cursor.local_date)
        if after:
            condition |= Q(local_date__gt=cursor.local_date)
            condition |= Q(local_date__isnull=True)
        else:
            condition |= Q(local_date__lt=cursor.local_date)

    if cursor.local_start_time is None:
        time_prefix = date_prefix & Q(local_start_time__isnull=True)
        if not after:
            condition |= date_prefix & Q(local_start_time__isnull=False)
    else:
        time_prefix = date_prefix & Q(
            local_start_time=cursor.local_start_time
        )
        comparator = (
            {"local_start_time__gt": cursor.local_start_time}
            if after
            else {"local_start_time__lt": cursor.local_start_time}
        )
        condition |= date_prefix & Q(**comparator)
        if after:
            condition |= date_prefix & Q(local_start_time__isnull=True)

    id_comparator = (
        {"id__gt": cursor.event_id}
        if after
        else {"id__lt": cursor.event_id}
    )
    condition |= time_prefix & Q(**id_comparator)
    return condition


def select_balanced_race_dates(
    before_desc: list[date],
    anchor: date,
    after_asc: list[date],
    *,
    side_size: int = RACE_DATE_WINDOW_SIDE_SIZE,
    limit: int = RACE_DATE_WINDOW_LIMIT,
) -> list[date]:
    """在锚点两侧平衡挑选实际比赛日。

    输入为已排序且唯一的日期序列：``before_desc`` 倒序（离锚点由近及远）、
    ``after_asc`` 升序。规则：先取前 ``side_size``、锚点、后 ``side_size``；
    一侧不足时从另一侧按离锚点由近及远补足；输出升序、唯一、不超过
    ``limit`` 且必含 ``anchor``（通用 ``limit`` 下若超长，按离锚点距离裁掉
    最远日期但保留锚点）。不造无赛事自然日。
    """
    before = list(dict.fromkeys(before_desc))
    after = list(dict.fromkeys(after_asc))
    selected_before = before[:side_size]
    selected_after = after[:side_size]
    before_shortfall = side_size - len(selected_before)
    after_shortfall = side_size - len(selected_after)
    if before_shortfall > 0:
        selected_after = after[: side_size + before_shortfall]
    if after_shortfall > 0:
        selected_before = before[: side_size + after_shortfall]
    combined = list(dict.fromkeys([*selected_before, anchor, *selected_after]))
    if len(combined) > limit:
        combined = sorted(
            combined,
            key=lambda day: (abs((day - anchor).days), day),
        )[:limit]
    return sorted(combined)


def public_default_race_date_window(queryset, *, today: date) -> DefaultRaceDateWindow:
    """在已筛选公开 queryset 上计算默认日期窗口。

    只承认有 ``local_date`` 的实际比赛日，发出恰好两条有界聚合查询：

    - ``local_date <= today`` 按日期倒序最多 11 个 distinct 日期，并以
      ``Min("id")`` 聚合出该日代表赛事 ID；
    - ``local_date > today`` 按日期升序最多 11 个，同样带代表 ID。

    锚点：历史侧首项 == ``today`` 时锚定 ``today``；否则未来侧首项；否则
    历史侧首项；两侧皆空则无锚点。queryset 不得携带 read-gate 展示
    annotation（``public_current_result_revision_id`` /
    ``public_projection_write_owner``），即日期聚合在加这些 annotation
    之前的基础 queryset 上执行。
    """
    dated = queryset.filter(local_date__isnull=False)
    before_rows = list(
        dated.filter(local_date__lte=today)
        .values("local_date")
        .annotate(representative_id=Min("id"))
        .order_by("-local_date")[:RACE_DATE_WINDOW_LIMIT]
    )
    after_rows = list(
        dated.filter(local_date__gt=today)
        .values("local_date")
        .annotate(representative_id=Min("id"))
        .order_by("local_date")[:RACE_DATE_WINDOW_LIMIT]
    )
    if before_rows and before_rows[0]["local_date"] == today:
        anchor = today
    elif after_rows:
        anchor = after_rows[0]["local_date"]
    elif before_rows:
        anchor = before_rows[0]["local_date"]
    else:
        return DefaultRaceDateWindow(anchor=None)
    before_desc = [row["local_date"] for row in before_rows if row["local_date"] != anchor]
    after_asc = [row["local_date"] for row in after_rows if row["local_date"] != anchor]
    dates = select_balanced_race_dates(before_desc, anchor, after_asc)
    representative_by_date: dict[date, int] = {}
    for row in [*before_rows, *after_rows]:
        representative_by_date.setdefault(row["local_date"], row["representative_id"])
    return DefaultRaceDateWindow(
        anchor=anchor,
        dates=dates,
        representative_ids=[representative_by_date[day] for day in dates],
    )
