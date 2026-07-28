# 未来七天重点赛事官方出走时刻与出马表规格

## 当前状态

本 change 仅完成探索、规格与方案审核，不包含实现授权。生产只读盘点、官方页面人工核验和
来源条款研究不构成候选生成或数据库写入授权。

## 窗口合同

- 项目约定时区：`Asia/Shanghai`。
- 冻结执行时刻及窗口：
  `[2026-07-27T01:50:01+08:00, 2026-08-03T01:50:01+08:00)`。
- 对应 UTC：
  `[2026-07-26T17:50:01Z, 2026-08-02T17:50:01Z)`。
- 枚举阶段先查询各地区本地日期 `2026-07-26..2026-08-03` 的超集；只有获得带 IANA
  时区的官方出走时刻并换算为绝对时间后，才决定是否真正落入半开窗口。
- 原始值、官方原始时区、规范化 UTC、赛事地区时区和中文展示值必须同时保留。英国、法国、
  美国按赛事日期使用 IANA 时区处理 DST，禁止写死 UTC offset。

## “应到”重点赛事定义

以现有产品规则为唯一枚举入口，不先挑赛事：

1. `RaceEvent.is_key_race == true`，即 `priority in {P0, P1}` 或 `is_featured=true`；
2. `visibility_status=published` 且 `status != cancelled`；
3. 枚举阶段不排除 `race_series is null` 或未批准 series，而是把原值写入 snapshot；
   apply 阶段才要求 `RaceSeries.review_status=approved`，缺 series 或未批准者形成 blocker；
4. 赛事本地日期落入窗口查询超集；
5. 最终以官方出走时刻的 aware instant 判断是否落入冻结的 `[start, end)`。

生产只读盘点得到 19 条候选：英国 8、美国 10、法国 1；日本、香港和其他地区为 0。
19 条均无 `race_datetime`、无 `local_start_time`、无 `RaceEventRunner`。在官方时刻未确认前，
“19”是应核验超集，不是最终可应用数量。

可重放 snapshot 为 `inventory_snapshot_20260727.json`，SHA-256
`cc87c32cb56f75af43f7d67a8beb281385f99c781549e38ac9e462143e14a319`；其
`query_contract_version=upcoming_key_race_inventory_v1`，包含精确提取时间、生产
revision、逐行 eligibility 原值、series 身份、时区和 runner 计数。

## 功能要求

### 1. 来源与权威

- 每个字段绑定
  `provider / region / field / result_phase / provider_contract_version`；当前真实 phase
  使用 `RaceResultPhase.RACECARD`，赛前具体语义另存在 field provenance 中。
- 第三方 API 只能作为发现或补充信号，不能标成官方权威。
- 来源合同必须包含 URL/端点、稳定赛事 ID、字段语义、公布与修订时点、访问限制、
  条款证据和核验时间；缺任何一项 fail closed。
- 当前已审核的 BHA、France Galop、Equibase route 只覆盖赛果，不授权自动抓取赛前
  entries/racecard；本 change 不得静默扩展旧合同。

### 2. 时间语义

- `scheduled_post_time`：官方赛前公布的计划发走/开跑时刻。
- `actual_off_time`：赛后或实时来源确认的实际发走时刻。
- `local_start_time`：官方公布的场地本地 wall-clock，仅作展示与对账，不单独代表绝对时刻。
- `race_datetime`：带时区证据换算后的绝对时刻，数据库按 UTC 保存。
- 本批赛前任务只可把 `scheduled_post_time` 映射到 `race_datetime`；不得把计划时间伪称
  `actual_off_time`。规范观察与 revision 的 phase 为现有 `racecard`，并在
  `field_provenance.time_semantics=scheduled_post_time` 标明语义。中文展示按
  `Asia/Shanghai` 生成，但不得覆盖原始值。

### 3. 身份对齐

- 赛事必须以官方稳定外部赛事 ID、官方场次、场地、官方日期和时间证据联合对齐；
  禁止仅按名称/日期模糊匹配。
- 出马必须以 `RaceResultSourceIdentity` 命名空间内的官方 runner/horse ID（如来源提供）
  及该场官方马号对齐；马号本身不可跨修订作为唯一身份。
- 保留马号、官方原名、状态、骑师、练马师及来源实际提供的其他字段；缺失字段保持空，
  不猜值。
- 官方未提供稳定 runner/horse ID 时，整场不可自动 apply，只生成 blocker。
- canonical 身份为 `RaceEventParticipant` +
  `RaceEventParticipantSourceIdentity`；`RaceEventRunner` 只是 current racecard 的 legacy
  projection，不承担跨来源身份。

### 4. 候选与证据

抓取层不得写 `RaceEvent` 或 `RaceEventRunner`。它只可：

1. 把官方响应写入不可覆盖的来源缓存；
2. 生成不可变候选 artifact；
3. 输出来源 URL、获取时间、冻结窗口、原始/规范化/中文值、字段 diff、SHA-256、
   地区/赛事覆盖统计和逐项 blocker；
4. 以独立 verifier 校验 artifact、来源缓存和清单哈希。

空表、局部表、身份冲突、时间冲突、不可信来源、条款或合同不完整时整场 fail closed，
不可生成可 apply 的半成品。

### 5. 审核与 apply

- 顺序固定为：prepare → dry-run → 字段级人工 review → coverage audit →
  锁定 artifact SHA → transaction apply → 独立 verify。
- apply 必须显式传入独立 approval receipt 的 SHA；receipt 只能从不可更新/删除的数据库
  approval row 导出，该 row 由已认证 Admin reviewer 动作创建，并绑定 artifact manifest、
  inventory、source contracts、批准人、批准时间、范围与结论。命令行现场计算任意 artifact
  SHA 或手填 staff ID 不构成批准。
- apply 使用 `RaceEventProjectionControl` 互斥和单事务；任一冲突整批回滚。
- 重放相同 SHA 必须为幂等 noop；不同 SHA 修改同一批次时必须重新审核。
- 空值不得覆盖既有更完整且来源权威不低的非空字段。
- 写前/写后按地区、赛事、字段和 runner 状态计数，并生成 CAS rollback manifest。

## 当前确认与缺口

- 官方赛程来源可以证明这 19 条数据库赛事的日期与级别来源。
- 研究性人工浏览确认美国部分赛事已有官方 entries 和计划 post time，但 Equibase 条款与
  当前 route contract 不允许把这些页面转成自动化候选或 apply artifact。
- 英国官方动态页当前没有可用的结构化 racecard；法国公开赛前页需要登录；美国 8 月 1 日
  的部分页面在证据时点仍未发布。
- 因此当前没有任何一场同时满足“官方、机器可用、条款允许、稳定 ID、完整出马表、可审计
  artifact”全部门禁，可 apply 数为 0。

## 非目标

- 不启用 Celery beat、race-live scheduler、monitor 或公共发布。
- 不购买订阅、不签署数据许可、不使用生产 secret。
- 不写生产数据库，不把人工浏览结果手工抄入业务表。
- 不修改赛果、赛事生命周期或历史赛事恢复任务。
- 不把本 change 的方案审核当成实现、联网、生产 apply 或发布授权。
