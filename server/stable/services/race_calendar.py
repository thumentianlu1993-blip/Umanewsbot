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
from datetime import date

from django.db.models import Min

RACE_DATE_WINDOW_SIDE_SIZE = 5
RACE_DATE_WINDOW_LIMIT = 11


@dataclass(frozen=True)
class DefaultRaceDateWindow:
    """默认模式选定的日期窗口；无公开比赛日时 anchor 为 None、列表为空。"""

    anchor: date | None
    dates: list[date] = field(default_factory=list)
    representative_ids: list[int] = field(default_factory=list)


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
