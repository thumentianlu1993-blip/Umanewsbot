# 2026-07-27 未来七天重点赛事生产只读清单

## 证据边界

- 精确提取时间：`2026-07-26T18:15:49.235913+00:00`，即上海
  `2026-07-27T02:15:49.235913+08:00`。
- 生产 revision：`a59956b327157d29630fab1f1c98ba9c9cacfed0`，与当时 `origin/main` 一致。
- 查询只读，没有修改生产数据库、配置、任务或队列。
- 机器 snapshot：
  `inventory_snapshot_20260727.json`，SHA-256
  `cc87c32cb56f75af43f7d67a8beb281385f99c781549e38ac9e462143e14a319`。
- 窗口：
  `[2026-07-27T01:50:01+08:00, 2026-08-03T01:50:01+08:00)`；
  UTC `[2026-07-26T17:50:01Z, 2026-08-02T17:50:01Z)`。

## 枚举结果

查询合同 v1：

```python
(
    RaceEvent.objects.filter(
        local_date__gte="2026-07-26",
        local_date__lte="2026-08-03",
        visibility_status=RaceEventVisibility.PUBLISHED,
    )
    .exclude(status=RaceEventStatus.CANCELLED)
    .filter(priority__in=[RaceEventPriority.P0, RaceEventPriority.P1])
    |
    RaceEvent.objects.filter(
        local_date__gte="2026-07-26",
        local_date__lte="2026-08-03",
        visibility_status=RaceEventVisibility.PUBLISHED,
        is_featured=True,
    ).exclude(status=RaceEventStatus.CANCELLED)
).distinct()
```

枚举不以 series approval 过滤；snapshot 保留 `race_series_id/series_review_status`，缺 series
或未批准 series 在 apply 阶段 blocker。本次 19 行均为
`published / not cancelled / approved series / P0 or P1`，且当前
`race_datetime=null / local_start_time=null / runner_count=0`。

| ID | 本地日期 | 地区 | 赛事 | 等级/优先级 | 场地时区 |
|---:|---|---|---|---|---|
| 426 | 2026-07-26 | 美国 | Eddie Read S. | G2 / P1 | America/Los_Angeles |
| 427 | 2026-07-26 | 美国 | Honorable Miss S. | G2 / P1 | America/New_York |
| 929 | 2026-07-28 | 英国 | Al Shaqab Goodwood Cup | G1 / P0 | Europe/London |
| 930 | 2026-07-28 | 英国 | HKJC World Pool Lennox | G2 / P1 | Europe/London |
| 931 | 2026-07-28 | 英国 | Coral Vintage | G2 / P1 | Europe/London |
| 932 | 2026-07-29 | 英国 | Visit Qatar Sussex | G1 / P0 | Europe/London |
| 935 | 2026-07-30 | 英国 | Qatar Nassau | G1 / P0 | Europe/London |
| 937 | 2026-07-30 | 英国 | Markel Richmond | G2 / P1 | Europe/London |
| 428 | 2026-07-30 | 美国 | Glens Falls | G2 / P1 | America/New_York |
| 938 | 2026-07-31 | 英国 | King George Qatar | G2 / P1 | Europe/London |
| 429 | 2026-07-31 | 美国 | Amsterdam | G2 / P1 | America/New_York |
| 940 | 2026-08-01 | 英国 | Qatar Lillie Langtry | G2 / P1 | Europe/London |
| 430 | 2026-08-01 | 美国 | Clement L Hirsch | G1 / P0 | America/Los_Angeles |
| 431 | 2026-08-01 | 美国 | Saratoga Special | G2 / P1 | America/New_York |
| 433 | 2026-08-01 | 美国 | Jim Dandy | G2 / P1 | America/New_York |
| 434 | 2026-08-01 | 美国 | Beverly D | G2 / P1 | America/New_York |
| 435 | 2026-08-01 | 美国 | Arlington Million | G1 / P0 | America/New_York |
| 436 | 2026-08-01 | 美国 | Secretariat | G2 / P1 | America/New_York |
| 740 | 2026-08-02 | 法国 | Prix Rothschild | G1 / P0 | Europe/Paris |

## 地区覆盖

| 地区 | 应核验 | 官方赛程已证实 | 自动化官方赛前合同 | 当前可 apply |
|---|---:|---:|---:|---:|
| 英国 | 8 | 8 | 0 | 0 |
| 美国 | 10 | 10 | 0 | 0 |
| 法国 | 1 | 1 | 0 | 0 |
| 日本 | 0 | 0 | 不适用 | 0 |
| 香港 | 0 | 0 | 不适用 | 0 |
| 合计 | 19 | 19 | 0 | 0 |

7 月 26 日两场美国赛事只有在官方 post time 晚于窗口 start 时才纳入最终批次；8 月 2 日法国
赛事只有在官方 aware post time 早于窗口 end 时才纳入。人工研究观察两场美国赛事在窗口内，
但该观察不能替代可 apply 的合规官方 artifact。
