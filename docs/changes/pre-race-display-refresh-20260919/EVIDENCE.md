# 只读排查证据与边界

核验时间：2026-09-18 18:43 UTC起（北京时间9月19日02:43）。此文件不表示已修复。

## 运行态与页面

- 生产web版本文件：`433de627b9ae4d9c0c756dd518668a115a818bd8`。主线`5731ae6e`包含该归一化实现及发布文档。
- 八容器运行，web/db/redis健康；公开event491页面HTTP200，重现截图展示。
- 只读Django事务使用`SET TRANSACTION READ ONLY`及20秒statement timeout；12个明确目标，不扫描或导出私有配置。业务开关enabled/network/scheduler/future-discovery/JRA/racecard-apply均true，已启用字段包含participants.odds/popularity/status。

| 目标 | 当前实际路径 | 观察 |
|---|---|---|
| 491赛马会金杯 | reviewed_pre_race候选40396；无enrollment、runner或checkpoint | 9月18日03:42 UTC补录7行，均declared、赔率0条；18:37 UTC有TRA身份检查成功，未改此候选 |
| 492、494、495、770、771、969 | 其余参考候选；无enrollment、runner或checkpoint | 存在近期TRA身份检查，名单仍为03:42–04:12 UTC补录快照 |
| 191白山大赏典 | NAR人工候选40404，12行 | 没有赛前检查状态及enrollment |
| 772 | 已纳管，data_sync/current_racecard_revision=52 | 16:17 UTC纳管，8行canonical，18:19 UTC最近racecard/race_time成功；不能把全部自动链判为停止 |
| 103、104、105 | JRA自动预览候选 | 最近有JRA成功检查；未改变内容时仍复用旧候选，候选fetched_at不是last_checked_at |

- 491原始参赛条件为`3U 3UP R D L`，严格解析未识别完整语义，展示层输出“待核实”。
- 37条2026年起published、排除active canonical duplicate的赛事：`race_datetime`为空，local_date/local_start_time都有值；37条timezone_name均为Asia/Shanghai。方案兼容此已知结构，避免只按nullable UTC排序遗漏。
- 两次103采样（18:43、18:44 UTC）均为last_success18:27:07，next_poll18:37:07；Beat入口在7/17/27/37/47/57分。支持时隙错位风险，不等价证明每条任务都是固定20min。
- 有界Docker日志未取得相关task行，不把日志无结果当作任务未运行的证据；未手工派发任务，未调用付费数据源。

## 当前来源对照

[NYRA官方本场](https://www.nyra.com/belmont/racing/entries/?day=2026-09-18&limit=entries&race=5)的日期、场地、Race5、距离/等级与event491一致。7匹原始报名中3/5/6号标SCR（Chunk of Gold/Banishing/Render Judgment），其余4匹非SCR；纽约16:14对应北京9月19日04:14。原件抓取的SCR计数为3。源还显示ML标签，不应直接宣传成实时盘口。

[站内详情](https://umafans.run/races/2026/us-toba-2026-0918-282/)实际7条均“已出走登记”，赔率“— / —”。

## 对应代码

- `server/stable/services/race_information_display.py:_time_fields`：当前输出当地日期/时间并拼北京时间。
- `server/stable/views.py:_race_time_label/_public_race_status_label/_race_calendar_queryset/_build_race_calendar_groups`：存在另一套时间标签，query/group按当地日期。
- `server/stable/services/race_calendar.py`：窗口查询与v1复合游标保存local_date/local_start_time。
- `server/stable/templates/stable/public/race_detail.html`：条件卡片按原始eligibility_text非空渲染。
- `server/stable/services/race_pre_race.py:public_reviewed_preview`：标题追加来源/人工核验，赔率及热门排名硬编码空；没有该人工候选的自动网络刷新入口。
- `race_pre_race.py:parse_jra_card/public_jra_preview`：未采集动态退赛/赔率，预览状态declared。
- `race_data_sync_providers.py:discover_the_racing_api_source_identities`：匹配失败记录诊断计数，但循环末对检查完成的event调用finish_pre_race成功；不是racecard已刷新。
- `server/app/settings.py`：future-discovery十分钟触发；`race_data_sync_policy.calculate_next_poll_at`从now加周期，now在finish为完成时刻。

完整本轮只读命令/摘要及官方、公网页缓存位于`/tmp/pre-race-plan-20260919`。仅将这些脱敏结论写入仓库；来源快照不等于获准自动采集或已上线。
