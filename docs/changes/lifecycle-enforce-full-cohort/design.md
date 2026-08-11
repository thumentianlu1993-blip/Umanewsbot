# 生命周期全量 enforce cohort 设计

## 1. 现状与根因

当前 `true/enforce` 是端到端 exact-two canary：settings、manifest loader、promotion、activation、
scanner、单场 task、部署脚本和测试均要求恰好两个 ID。更严重的是，每个单场任务都会重新查询并
锁定完整 canary cohort。把 ID 列表机械扩成数百场会形成 O(N²) 行读取和全局串行锁。

strict v2 enrollment 已提供可复用的 1–20 场、false/off、shadow-only、manifest-bound 原子入口；
claim/apply 已提供 `skip_locked`、token/generation/TTL、状态与审计同事务、dedupe 和缓存失效。

## 2. 架构

```text
eligible census
  -> strict v2 enrollment batches (<=20, missing controls only)
  -> full registry artifact (all members, multiple enrollment SHAs)
  -> promotion batches (<=100, enforce/inactive)
  -> whole-registry verify
  -> atomic registry activation
  -> Beat scanner (<=100 claims/tick)
  -> per-event O(1) membership validation
  -> existing lifecycle decision/apply
```

新增通用 `race_event_lifecycle_enforce.py`，保留 legacy canary service 用于读取历史证据和关闭/迁移
兼容。通用 artifact 冻结：schema/policy、approved commit、generation、predecessor SHA、生成/应用有效期、
成员数、membership SHA，以及逐场 event/control/schedule/enrollment 快照。逐场 evidence 只保存 root SHA、
membership SHA、entry SHA、batch SHA、activation 状态/ID，不复制完整 ID 列表。

## 3. 持久化与唯一 active 根

本 change 明确新增 migration 和两个结构化模型：

- `RaceEventLifecycleEnforceRegistry`：`root_sha256`（唯一）、`generation`（唯一递增）、
  `predecessor`、`membership_sha256`、`member_count`、`state`、`is_active`、`activation_id`、
  `approved_commit`、`selector_scope`、`scope_sha256`、`census_cutoff`、`apply_expires_at`、
  `runtime_valid_until`、artifact receipt 和时间戳；
  PostgreSQL 条件唯一约束 `UniqueConstraint(fields=["is_active"], condition=Q(is_active=True))`
  保证至多一个 active registry。
- `RaceEventLifecycleEnforceMembership`：`registry`、`event`、`entry_sha256`、source enrollment SHA、
  schedule generation/hash、地区/时区和必要冻结快照；`UniqueConstraint(registry,event)`，并为
  `(registry,event)`、`(registry,state/event)` 运行查询建立索引。

activation 在单事务取得 advisory lock、锁定当前 active/predecessor/target registry，重算
`eligible_at_cutoff ∩ frozen_scope`，验证 count/digest 后执行 predecessor active→retired 与 target
inactive→active CAS。`OperationLog` 仅作审计，
不承担唯一性或运行授权。单场 task 通过 active registry 和 `(registry,event)` membership 做常数条查询，
再核对 control/event schedule；control JSON 不能独立授予权限。

## 4. 兼容与升级

- event 186 已 finished：保留旧 canary evidence/transition，不进入 scheduled census；
- event 187 若仍 scheduled 且快照合法，可作为新 registry 成员，promotion 受控替换运行 evidence，
  历史 canary provenance 不重写；
- 旧双赛事运行态必须先在共享锁内收敛到 `false/off` 并 disarm，再部署/prepare 新 registry；
- 新旧 trust root 不得同时非空；runtime coherence 必须逐服务精确一致。
- legacy 186 control 在 disarm 后降为 shadow/terminal、清空运行 claim 和 `next_refresh_at`，但保留独立
  `enforce_canary` 历史 evidence；event 187 若迁入 registry，运行授权写入 membership 表，不覆盖历史
  transition metadata。
- successor activation 与 predecessor retirement 同事务；predecessor-only controls 降为 shadow，
  清除过期/未消费运行 claim并按当前状态重算 `next_refresh_at`。scanner 只从 active membership join claim，
  绝不按所有 `mode=enforce` 扫描。

## 5. E1 census 与人工 successor

E1 selector 在 aware UTC `census_cutoff` 只读扫描全部候选并输出 included/blocked/blocked_by_scope 明细。
每个 artifact 冻结上述四种 allowlisted canonical `selector_scope` payload 和 `scope_sha256`，字段固定为：

- `kind`、UTC `cutoff/window_end`、start/end inclusive flags；
- `require_datetime`、升序唯一 `explicit_event_ids`；
- `limit`、固定 `order_by=["race_datetime","event_id"]`；
- `predecessor_carry_forward`。

`datetime_7d_canary` 使用 `cutoff <= T < cutoff+7d`、limit 20；`datetime_30d` 使用
`cutoff <= T < cutoff+30d`、limit 100，并先保留 predecessor 中仍合格成员，再按上述顺序补足剩余名额；
若 predecessor 已超过新 limit则 prepare 失败而不是截掉授权。`no_time_canary` 继承 predecessor 中仍合格
成员，再加入 artifact 明确冻结的少量无时间 event IDs；`full_eligible` 无 limit，包含全部合格成员。
`scope_sha256=SHA256(canonical selector payload)`。缺 control 的
included 赛事按 20 场拆分 strict v2 enrollment；随后生成累计 registry。activation 前在同一 advisory
lock 内重算所有 `updated_at <= census_cutoff` 的资格与 scope 交集，必须与 artifact 完全一致；成员快照
漂移失败。只有 `full_eligible` scope 才断言全库合格集合守恒。
cutoff 后创建或更新的赛事只进入 successor pending，不使旧 artifact产生竞态缺员。

发布采用 7 天有时间样本、30 天、全部 cutoff 合格赛事三档 predecessor-bound generation。E1 以后新增
覆盖通过受审人工 successor 批次完成。旧 v1 auto-discover 不可达；自动 admission 明确拆为后续 change。
无时间赛事在 `no_time_canary` generation 真实验收；该 generation carry forward 既有 datetime 授权，
验收前无时间样本不属于 active scope，不在 active registry 中制造“inactive membership”。

## 6. 时间有效期

每场 authority boundary：有时间为 UTC `race_datetime + 30m`；无时间为赛事 IANA 当地日期次日
`00:00` 转 UTC。registry `runtime_valid_until` 固定为 `generated_at + 35d`，且不得超过 45 天；成员可以
晚于该时间，但必须在到期至少 72 小时前生成并激活 successor 才能在其边界获得写权限。scanner 在
claim 前、task 在事务内都校验 registry 未过期；过期零 claim/零 applied并记录可观测 reason。无时间
赛事同样遵守此规则，DST 由 `ZoneInfo` 转换。

## 7. 并发、性能与失败恢复

- promotion 使用共享 host release lock + PostgreSQL advisory transaction lock；批内 event/control 排序
  `select_for_update`，失败整批回滚；最终 activation 在事务内重算 cutoff census、校验完整 count/digest、
  retirement/activation CAS；普通赛事实体写不持 host lock，因此以 `updated_at/cutoff` 和冻结快照解决竞态；
- promotion 的 mandatory backup 之前先停止 Beat、按冻结 worker node drain active/reserved，再停止 worker；
  从快照完成到 registry promotion 不存在 lifecycle 写者。legacy disarm 使用旧 artifact 自带的独立
  approved commit，不复用新 release commit；
- promotion 成功态明确保留 Beat stopped。registry enable admission 接受这一严格状态，仍须 web/worker
  false/off coherence，且 Beat 只在 DB/env 四元 root 与 web/worker 验证全部成功后最后启动；
- activation 后 env/rebuild 失败时先收敛 false/off；同 artifact 重试强校验 raw root、membership digest、
  member count 后复用数据库既有 activation ID，不生成冲突 ID。最终 verifier 同时核对 resident env 与
  DB 的 root/membership/count/activation；
- scanner 只做一次 registry active root 验证，然后复用现有 batch claim；单场 task 不允许 `IN` 全成员；
- stale queued task 携带 root SHA + activation ID，registry rotation/off 后在事务内零写并释放/过期 claim；
- 目标性能：scanner 查询量随 tick/batch 有界；单场 apply 查询/锁与 registry 成员数无关；
- 任何 root/count/membership/schedule/generation/region/timezone 漂移、范围外 applied、重复 applied、
  claim 泄漏、服务/缓存异常均切 `false/off`；不反向改已合法状态。

## 8. 预计文件

- `server/stable/services/race_event_lifecycle_enforce.py`（新增）；
- `server/stable/models.py` 与新增 migration（registry/membership/约束/索引）；
- `server/stable/services/race_event_lifecycle.py`、`server/stable/tasks.py`；
- `server/app/settings.py`、`.env.example`；
- prepare/promote/verify registry 管理命令；
- `deploy/promote_lifecycle_enforce_registry.sh`（新增）；
- `deploy/switch_lifecycle_mode.sh`、`deploy/verify_lifecycle_runtime_coherence.sh`、
  `deploy/deployment_lock.sh`；
- application/operations/PostgreSQL 测试；
- 本 change 文档和实际受影响的 current_state/decisions/deploy_runbook/project_status。
