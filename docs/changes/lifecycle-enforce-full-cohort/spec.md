# 生命周期全量 enforce cohort 规格

## 1. 目标

在 event 186 双边界 canary 已验证成功的基础上，把生命周期从“恰好两场 canary”升级为
可扩展的全量 enforce 能力，使系统内符合资格的赛事不因 `priority`、`is_featured` 或
`is_key_race` 而被排除。

本 change 只交付 E1：以冻结 census 覆盖该 census cutoff 时全部合格赛事，分批
enrollment/promotion，统一激活一个 registry；后续新增或在 cutoff 后变为合格的赛事进入
successor pending 集合，由同一受审人工批次生成 predecessor-bound registry。

持续自动 admission（E2）的触发频率、任务 owner、每日上限、artifact 审批、重试和通知属于后续
独立 change。本 change 不能被表述为“永久自动全量”。

## 2. 资格规则

赛事纳入 lifecycle enforce 必须同时满足：

- `visibility_status=published`；
- `status=scheduled`；
- `local_date` 存在；
- 地区属于日本、中国香港、英国、法国或美国；
- `timezone_name` 满足地区 IANA 合同，美国赛事还必须命中受审 allowlist；
- `manual_lock_flags` 为空，control 的 `manual_pause_reason` 为空；
- 有 `race_datetime` 时必须为 aware datetime；无时间时按赛事当地日期次日零点规则推进；
- control 不存在时通过 strict v2 enrollment 创建，存在时必须具有合法且未漂移的 enrollment
  provenance。

`priority`、`is_featured`、`is_key_race` 只保留为审计字段，不是资格门禁。取消、延期、已完赛、
未发布、未知地区、错误时区、缺日期或人工锁定赛事不进入新 cohort，并必须按原因计数。

## 3. 全量语义

- 每个 registry 冻结 canonical `selector_scope` payload 与 `scope_sha256`；payload 至少包含
  `kind/cutoff/window_end/start_inclusive/end_inclusive/require_datetime/explicit_event_ids/limit/order_by/`
  `predecessor_carry_forward`。census 必须满足
  `included + blocked_by_reason + blocked_by_scope = inspected`，成员集合精确等于
  `eligible_at_cutoff ∩ frozen_scope`。
- scope 依次只允许 `datetime_7d_canary`、`datetime_30d`、`no_time_canary`、`full_eligible`；
  只有最终 `full_eligible` generation 的成员数、有序摘要与 cutoff 时全部合格集合完全一致，才可称为
  E1 全量。
- 7/30 天窗口按 UTC aware `race_datetime` 计算，`cutoff <= T < window_end`；候选按
  `(race_datetime ASC,event_id ASC)` 稳定截断。30 天和无时间 generation 必须携带 predecessor 中仍合格
  成员；无时间样本使用 artifact 中明确受审的升序唯一 ID。`scope_sha256` 对完整 canonical payload 求摘要。
- 不允许只覆盖“已有 control”却宣称覆盖全部赛事；缺 control 的合格赛事必须先按每批最多 20 场
  strict v2 enrollment。
- promotion 每批最多 100 场，但最终 activation 只能在完整 registry 全员通过后发生；部分批次
  不能获得公开状态写权限。
- 人工 successor 批次每次生成新的 registry generation，冻结 predecessor SHA；不得原地修改旧 artifact。
- cutoff 后新增或 `updated_at` 发生资格变化的赛事进入 successor pending，不构成本 generation 缺员；
  activation 前必须重算 `updated_at <= census_cutoff` 的资格集合与 frozen scope 交集并与 registry 精确相等。

## 4. 运行时安全合同

- 全局 `true/enforce` 必须绑定数据库唯一 active registry SHA、membership SHA、成员数和 activation ID；
- scanner 每次最多 claim 既有 `RACE_EVENT_LIFECYCLE_BATCH_SIZE`，不得全表高频读取；
- 单场 advance 只锁该 event/control，并以 O(1) registry root + 单场 membership evidence 验证权限；
- 旧 root、inactive、伪造 membership、错误 activation、过期/漂移 schedule 或范围外 enforce control
  均零 claim或零 applied；
- 状态更新、applied transition 和 control 成功记录同事务；重复投递最多产生一次有效转换；
- 切回 `false/off` 后已排队任务必须在事务内失效；合法完成的公开状态不自动反向修改。

## 5. 非目标

- 不启动或改造 race-live；
- 不接入 provider、不抓取赛前资料或赛果；
- 不改变 provisional/official result 概念；
- 不发送 QQ、不发布新闻；
- 不复用旧 v1 `--auto-discover` apply；
- 不扩大五地区时区合同；
- 不批量修正历史已完赛赛事。

## 6. 验收标准

- event 186 的生产 canary 证据被保留，旧 `enforce_canary` transition provenance 仍可验证；
- 3 场以上、多个 enrollment SHA 的 registry 可完整 prepare/promote/activate/replay；
- 全量 census 守恒，范围外 enforce/applied 为 0；
- 250 个 due control 能按 `100/100/50` 有界处理且无重复；
- 单场 task 不读取或锁完整 registry；
- PostgreSQL 并发 promotion/claim/apply 无部分 cohort、重复转换或 claim 泄漏；
- 页面缓存、详情页和日历状态一致；
- failure path 可收敛到 `false/off`，race-live 保持关闭。
- 第一档必须至少有一场通过新 registry 真实跨越 T 与 T+30；无时间赛事扩大前必须另有一场真实
  当地次日转换证据，否则无时间成员保持 inactive。
