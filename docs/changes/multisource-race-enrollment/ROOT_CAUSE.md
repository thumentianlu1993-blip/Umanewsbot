# 2026-09-20 产经赏 All Comers 状态未推进根因

核验窗口：北京时间 15:11～15:17。范围：生产容器、只读数据库事务、有限 Redis 结果样本、已存在的供应商响应文件、JRA 公开详情和本站页面。没有触发任务、重新调用付费供应商、修改生产数据、重启或部署。原有本地未提交改动保留。

## 结论

赛事 104 没有进入状态管理范围。直接触发条件是 TRA 日本出马表返回空集合；结构性原因是日本自动登记依赖 TRA 身份，而已上线的 JRA 官方通道仅承接赛前资料。开赛后两个时间窗口又阻止漏登赛事补入，告警只覆盖已登记赛事，形成持续漏管。

官方结果已实际发布；生产任务也有成功运行记录。不能将这次问题归因于官方未出结果、总开关关闭、Beat 未启动或整个赛事队列积压。

## 当前生产证据

- 运行版本：`3a174b1e93c499f293deeabfff4dfa71b427a684`，release 目录 `/opt/umanews-release-3a174b1e-prerefresh-20260919/umanewsbot`。Web 镜像 `sha256:1622560c7f522d5078adbed5049e7bf7ab57e537bff57b97b37df0c83aec57a2`。
- Web healthy；Beat、普通 worker、`race_sync_v2_worker` 均运行约 33 小时。数据同步、发现、联网、生命周期、赛果应用及公开开关均为 true；旧生命周期模式为 enforce。
- 104：`jra-2026-0920-01`，开赛时间 `2026-09-20T06:45:00Z`，即日本 15:45／北京 14:45，时间和时区正确。15:16:45 北京时间复核仍为 `scheduled`，`result_confirmed_at=null`。
- 104 的 `RaceResultSourceIdentity`、`RaceDataSyncEnrollment`、`RaceEventProjectionControl`、`RaceEventLiveTracking`、`RaceEventLifecycleControl`、`RaceEventLifecycleTransition`、`RaceEventRevision`、`RaceEventResult` 均无记录，旧生命周期 registry membership 也不存在。正式 runners 为 0。
- JRA 赛前候选实际存在：候选 40409，13 匹、`numbered`、`validated=true`、`pending`；这不等于正式出马表或赛果接管完成。
- 14:27 与 14:47 的自然发现任务均 SUCCESS，但日本分组 `response_race_count=0`，104 的匹配原因为 `response_empty`。14:47 原始响应已从实际同步 worker 的 artifact 读取并核验 SHA：`region_codes=jpn`、`day=today`、`limit=500`、`skip=0`、`racecards=[]`、`total=0`。没有发生马名或马场匹配歧义。
- 14:45 和 14:51 的自然生命周期任务均 SUCCESS，`selected=0, transitioned=0, error=0`。任务成功仅表示函数执行结束，不能证明全部应管赛事已纳入。
- 15:15 队列采样：`celery=21`、`race_sync_v2=0`、旧隔离队列 `race_live=7543`。本次不处理旧队列。
- [本站详情](https://umafans.run/races/2026/jra-2026-0920-01/)仍显示“今天”，无赛果，并显示“本站暂未收录出马表”。
- 从当场 JRA 出马表的真实结果链接读取[官方赛果](https://www.jra.go.jp/JRADB/accessS.html?CNAME=pw01sde0106202604061120260920/92)：存在完整 13 匹着顺及払戻金，冠军为 8 号メイショウゲキリン。搜索索引中的年度重赏列表尚未补结果，不能用于否定实时详情。

完整有界证据见 [JSON](EVIDENCE.json)。

## 根因链与实际部署代码

代码定位均指上述生产提交，不指当前有大量未提交改动的本地旧分支。

1. **来源覆盖不闭环。** 生效 standing policy 的日本可登记路线只有 `the_racing_api / japan_jra` 和 `the_racing_api / japan_nar`；没有 JRA 官方赛果登记路线。身份发现调用 `racecards_free`，空响应无法生成来源身份。[调用点](https://github.com/thumentianlu1993-blip/Umanewsbot/blob/3a174b1e93c499f293deeabfff4dfa71b427a684/server/stable/services/race_data_sync_providers.py#L849)。原始空响应已证实；为什么供应商 free 端点没有日本数据，本轮未进一步调用其他套餐或端点验证，不能推断整个供应商无此比赛。
2. **状态更新被来源登记阻塞。** census 对没有唯一匹配来源的赛事返回 `source_identity_missing`，不能建立数据同步 owner 和生命周期控制。将当前数据库状态带入 14:40 的只读规则重放，104 明确得到该阻塞码。该重放用于证明分支，不冒充历史数据库快照。[登记准入](https://github.com/thumentianlu1993-blip/Umanewsbot/blob/3a174b1e93c499f293deeabfff4dfa71b427a684/server/stable/services/race_data_sync_enrollment.py#L620)。
3. **漏登没有赛后补入路径。** census 仅收 `cutoff <= race_datetime` 的有时间赛事，开赛即排除 104；TRA 身份发现又复用 `claim_pre_race()`，其 `in_window()` 在 T+5 分钟关闭。14:50 后再有官方或供应商数据，现有发现流程也不会为它补身份。15:14 的只读 census 中 104 已完全消失，而不是继续列为 blocked。[census 时间过滤](https://github.com/thumentianlu1993-blip/Umanewsbot/blob/3a174b1e93c499f293deeabfff4dfa71b427a684/server/stable/services/race_data_sync_enrollment.py#L468)、[T+5 窗口](https://github.com/thumentianlu1993-blip/Umanewsbot/blob/3a174b1e93c499f293deeabfff4dfa71b427a684/server/stable/services/race_pre_race.py#L59)。
4. **JRA 赛前接入没有完成赛后交接。** JRA 路径保存出马表候选、补赛时，但未建立结果来源身份、登记或生命周期。公开预览复用相同赛前窗口，T+5 后隐藏；因此候选明明有 13 匹，页面仍回退为没有出马表。[候选与赛时写入](https://github.com/thumentianlu1993-blip/Umanewsbot/blob/3a174b1e93c499f293deeabfff4dfa71b427a684/server/stable/services/race_pre_race.py#L263)、[预览窗口](https://github.com/thumentianlu1993-blip/Umanewsbot/blob/3a174b1e93c499f293deeabfff4dfa71b427a684/server/stable/services/race_pre_race.py#L320)。
5. **监控漏掉未登记赛事。** T+30 赛果 SLO 从 `RaceDataSyncEnrollment(state=enrolled)` 查询，104 不在检查集合。故当前监控无法覆盖“应登记但从未登记”的缺口。[SLO 查询](https://github.com/thumentianlu1993-blip/Umanewsbot/blob/3a174b1e93c499f293deeabfff4dfa71b427a684/server/stable/services/race_data_sync_alerts.py#L162)。

纯时间规则对已接管赛事会在 T 切 running、T+30 切 finished；这些规则本身不能跨越接管边界，也不能把 finished 等同于官方赛果确认。本次 15:16 的状态仍为 scheduled，已经超过其 T+30。

## 有界影响范围

9 月 12～21 日日本赛事采样中，昨日阪神跳跃锦标 103 也仍为 scheduled、无确认时间且没有自动登记；明日神户新闻杯 105 尚未登记，存在同类风险。100～102 已 finished 且有确认时间，但没有当前自动登记，不能据此证明常态自动化曾成功。

本轮没有做全球全部赛事普查，也没有验证 103 的完整逐步原因；其相同状态是影响样本，不扩大为所有日本比赛都失败。

## 修复方向与验收要求（尚未实施）

- 将 JRA 官方身份、完整赛果读取、正式确认和结果投影接入现有可信来源合同，使日本比赛不因 TRA free 缺数而完全漏管；沿当场真实结果链接发现 URL，不机械替换出马表 URL 参数。
- 生命周期覆盖与赛果来源可用性分别核算；若允许凭可信赛时接管状态，仍需明确状态写入权限，不能伪造来源身份或确认结果。
- 为未登记、尚未确认的近期赛事增加有界赛后发现／补入窗口；与已确认结果的 correction 观察区分。
- 告警分母涵盖“应纳管的公开赛事”，至少检测缺来源、缺登记、到时未转态、赛果逾期；不能只统计已登记集合。
- 保留已验证赛前候选的赛后可读性，明确最后更新时间及未接管状态。
- 回归至少覆盖：TRA 空响应但 JRA 有资料；赛前漏登后赛后补入；T/T+30 状态；官方完整赛果确认；未登记告警；跨 T+5 仍可读的出马表；不重复投影和不覆盖人工锁。

## 证据限制与操作边界

Redis 只扫描 6,000 个任务结果键，未扫完整库；展示的是实际命中的有界样本。原始 artifact 位于赛事同步 worker 的挂载中，Web 内同路径不存在，后在同步 worker 成功读取并核验，不把初次读取失败当作证据丢失。未运行任何 apply、补赛果、清队列或 provider 重试，也未改变马匹采集暂停状态。本次仅完成根因排查和仓库记录。
