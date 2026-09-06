# 补齐赛事状态自动更新完整链路：工程设计

## 1. 设计摘要

本变更不重建赛事系统。它修正现有 `race_sync_v2` 的两个断点：

1. standing policy 把多个可信来源放在同一组选项中且没有授予规则，导致没有来源身份的新赛事被批量判为路由歧义；
2. data-sync enrollment 与 lifecycle 固定 registry 是两套名单，新增赛事进入前者后仍进不了后者。

最小方案是：

- 将 standing policy 升级为 v2：可信来源按“先到先得”竞争首次纳管（一次性授予、`tiebreak_order` 固定平局、授予后粘滞），仅赛果能力来源只进更正渠道；
- 继续复用 `RaceDataSyncEnrollment`，把它作为新 data-sync 赛事的动态 lifecycle 准入证据；
- 新增一个共享的 lifecycle admission validator，供状态推进、赛果投影和公开读取共同使用；
- 保留旧 lifecycle registry 处理既有固定名单，不自动迁移历史；
- 不新增业务表，预计不需要数据库 migration。若实现时发现必须新增字段或约束，必须重新做方案审核。

## 2. 现有能力复用

| 现有对象 | 本方案如何复用 |
| --- | --- |
| `RaceEvent` | 继续作为公开赛事和状态真相 |
| `RaceResultSourceIdentity` | 继续保存 provider 赛事身份 |
| `RaceDataSyncEnrollment` | 继续作为 data-sync 纳管边界，同时成为新赛事 lifecycle 准入证据 |
| `RaceEventProjectionControl` | 继续保证只有一个 writer owner |
| `RaceEventLiveTracking` / provider checkpoint | 继续负责 claim、下一次轮询和 correction watch |
| `RaceEventLifecycleControl` | 继续负责时间状态调度；不增加第二套状态机 |
| `RaceEventLifecycleEnforceRegistry` | 保留给旧固定名单；不用于未来赛事自动扩容 |
| `RaceResultObservation` / `RaceEventRevision` | 继续承载不可变来源证据和赛果版本 |
| `RaceEventRevisionPublication` | 继续作为公开授权记录 |
| `RaceLiveAlertIncident` | 复用为阻断和超时告警，不新增通知渠道 |
| `audit_race_data_sync` | 扩展为产品验收和运行巡检入口 |

主要复用文件：

- `server/stable/services/race_data_sync_enrollment.py`
- `server/stable/services/race_data_sync_providers.py`
- `server/stable/services/race_data_sync_control.py`
- `server/stable/services/race_data_sync_lifecycle.py`
- `server/stable/services/race_data_sync_results.py`
- `server/stable/services/race_events.py`
- `server/stable/tasks.py`
- `server/stable/management/commands/audit_race_data_sync.py`
- `runtime/policies/race_data_sync/standing_policy.json`

## 3. 数据流

```text
每小时 future discovery
  -> 未来 30 天全量盘点
  -> 判断是否进入可信来源开放窗口
  -> 先到先得授予：身份唯一匹配、一次性授予、同轮 tiebreak_order 裁决
  -> 创建或轮换 RaceDataSyncEnrollment
  -> 建立 data-sync lifecycle admission

每分钟 selector
  -> 时间/出马表/赛果 checkpoint 到期
  -> 专用 race_sync_v2 worker 请求来源
  -> 保存 observation
  -> 事务内重验 enrollment、claim、来源、人工锁
  -> 写时间/出马表或正式赛果

每分钟 lifecycle
  -> 共用 lifecycle admission validator
  -> T 后进入 running
  -> T+30 后进入 finished

公开读取
  -> 共用 lifecycle admission validator
  -> 校验 publication/revision/enrollment/source
  -> 显示赛果
```

## 4. Standing policy v2

### 4.1 先到先得纳管

每条 route 新增：

```json
{
  "enrollment_eligible": true,
  "tiebreak_order": 1
}
```

- `enrollment_eligible`：来源具备完整能力（`race_time/racecard/result`）且已获许可，可以竞争首次
  纳管；只有 result 能力的来源必须为 `false`，只能进入更正渠道；
- `tiebreak_order`：地区内确定性平局顺序；同一轮盘点中多个来源同时命中同一赛事时按该顺序
  授予，结果写入审计，不随机。

每场赛事的纳管权只授予一次：

- 首个在合法请求窗口内返回完整合法响应且身份唯一匹配的 `enrollment_eligible` route 获得；
- 授予必须在单个事务内完成：按 event 加锁并使用唯一证据约束，并发授予竞争中只有一份
  enrollment 生效，其余重放为 noop；“先到先得”以事务提交先后定论，不依赖任务墙钟到达顺序；
- 授予后粘滞：后续 time/racecard/result 只接受获胜来源；其他来源的响应只保存 observation，
  经 correction 流程 supersede；
- 获胜来源失效（许可、route、身份或有效期）时 fail closed，赛事回到纳管池按同一规则重新授予，
  审计记录换手原因，禁止无记录接管；
- 获胜来源有效但在终态窗口内持续 not-found 或超出失败预算时，赛事进入 incident 与人工审核；
  经审核执行有审计的回池重授；仅赛果来源的数据只能经 observation -> revision 证据链采用，
  不允许无审核直接作为初始赛果写库。

policy 顶层同时把状态分为：

```json
{
  "new_enrollment_statuses": ["postponed", "scheduled"],
  "continuation_statuses": ["finished", "postponed", "running", "scheduled"]
}
```

前者决定哪些赛事可以第一次自动纳管；后者决定已经合法纳管的赛事是否可以继续走状态、赛果和更正链。

### 4.2 静态规则

- 每个支持地区必须至少有一条 `enrollment_eligible` route，否则整地区阻断（`trusted_route_missing`）；
- `enrollment_eligible` route 必须包含 `race_time/racecard/result`；
- result-only route 不参与 `build_race_data_enrollment_census()` 的纳管授予；
- 同一轮同一赛事多个来源命中时按 `tiebreak_order` 授予，审计记录全部候选与胜者；
- 来源优先级仍用于赛果更正仲裁，不再用于指定谁负责纳管。

这样可以从根本上消除“可信来源越多，纳管越容易歧义”的问题：竞争在时间上先后定论，同轮平局有
确定性顺序。

## 5. Future discovery 的分类与守恒

### 5.1 两份清单和两个窗口

- 未来清单：未来 30 天，所有公开赛事都必须被分类；
- 恢复清单：最近 7 天内已经 data-sync 纳管、tracking 开启，并存在未公开 official revision、开放 incident 或 correction watch 的赛事；
- 来源请求窗口：按当前 The Racing API 合同，只请求赛事当地的今天和明天。

盘点窗口内、请求窗口外的赛事记为 `awaiting_source_window`，不是 blocked。

恢复清单不把过去 7 天的全部赛事重新纳管，也不直接投影旧 revision；它只让仍有合法 tracking 责任的赛事进入 policy/enrollment/lifecycle 重新验证，并进入第 8 节的一次性审计修复流程。

### 5.2 明确分类

- `awaiting_source_window`
- `identity_ready`（保留词汇；首版由 `eligible` 覆盖，不单独产出）
- `eligible`
- `enrolled`
- `manual_lock_present`
- `trusted_route_missing`
- `trusted_route_invalid`（保留词汇；首版不产出，区域无可信 route 统一报 `trusted_route_missing`）
- `source_identity_not_found`（首版沿用既有 `source_identity_missing`）
- `source_identity_ambiguous`
- `writer_owner_conflict`
- `standing_policy_expired`
- `canonical_duplicate`
- `event_status_not_allowed`
- `continuation_status_not_allowed`

### 5.3 请求结果守恒

一次 discovery 必须满足：

```text
candidate_count
= already_valid
+ created
+ adopted
+ awaiting_source_window
+ unmatched
+ ambiguous
+ rejected
```

当前代码中“候选进入列表后，因为不是今天/明天而静默消失”的分支必须被消除。

### 5.4 身份匹配

继续只接受：

- 同一地区；
- 同一当地日期；
- 同一规范化马场；
- 赛事当前名称、已批准别名或已批准系列名称精确命中；
- 最终只有一个 provider race ID。

不新增模糊相似度，不用中文译名拆词猜测，不按日期和马场任选一场。

## 6. Data-sync lifecycle admission

### 6.1 共享校验器

新增一个唯一入口，例如：

```python
validate_data_sync_lifecycle_admission(
    *, event_id: int, now: datetime, lock: bool
) -> LifecycleAdmissionDecision
```

它必须验证：

- 总开关、scheduler 和 lifecycle apply 已开启；
- standing policy 文件与配置 SHA 一致且未过期；
- event 已公开，状态允许，没有人工锁；
- projection owner 为 `data_sync`；
- enrollment 为 `enrolled`，policy/route/entry/manifest/generation 与 control 一致；
- enrollment source identity 唯一且当前仍通过 route、条款、有效期和 registry 校验；
- enrollment 的授予来源与当前负责来源一致（纳管权粘滞），无未审计换手；
- lifecycle control 没有人工暂停；
- 没有同时存在一份适用于未结束赛事的 active legacy lifecycle membership；
- 需要写入时使用既有全局锁顺序，并在事务内重新验证。

这个入口必须同时被以下三处调用：

1. `advance_due_data_sync_lifecycle()`；
2. `apply_data_sync_result_observation()`；
3. `_resolve_data_sync_publication_from_loaded_rows()`。

任何一处自己复制一套判断都不通过 review，避免出现“数据库写成功但页面拒绝显示”或“页面显示但状态没有授权”。

### 6.2 生命周期 control 的建立

新 enrollment 成功时：

- 如果 lifecycle apply 未开启，只保存 enrollment，control 保持 `off`；
- 如果 lifecycle apply 已开启且没有 legacy membership/manual pause，则把 control 设为 `enforce`；
- 在 `manifest_data.race_data_sync` 写入 policy、manifest、entry 和 owner generation；
- `enrollment_manifest_sha256` 绑定当前 data-sync manifest；
- 设置正确的 `next_refresh_at`，但不立即伪造 transition。

新增一个有界 reconciliation service，处理“早已 enrolled、后来才开启 lifecycle”的情况。每批最多 20 场；只处理 standing policy 当前仍有效且证据完整的行。

### 6.3 与旧 registry 共存

- 有 active legacy membership 的赛事继续使用旧 registry；
- 没有 legacy membership 的 data-sync 赛事才使用新 admission；
- 未结束赛事同时命中两类授权时返回 `lifecycle_authority_conflict`；
- event 956 已结束且证据完整，不做历史迁移或重写；
- 旧 registry 的 retire 是未来独立治理任务，不包含在本期。

## 7. 时间变更与 admission 一致性

`race_datetime`、时区或状态被合法来源修改时，现有 schedule coordinator 已递增 lifecycle generation。

本方案要求同一事务同时：

- 清理旧 claim/token；
- 更新 `next_refresh_at`；
- 保留 enrollment 的稳定身份和 owner 证据；
- 更新 lifecycle control 中的当前 schedule generation；
- 让旧任务因 generation 不一致而零写退出。

初次 enrollment 的 `event_snapshot_sha256` 是采用当时的审计证据，不把它误当成赛事以后永远不变。当前值安全性由事务内 event、source、route、generation 和 manual lock 重验保证。

## 8. 停滞赛事审计修复

755/756/757 一类停滞赛事不等待新链的自然 provider 响应，改为一次性审计修复；该修复是独立
运维操作，可先于本变更发布窗口执行，不直接调用 result writer，也不修改 due time。

流程：

1. 最近 7 天未闭环清单找到现有未闭环 data-sync enrollment（已纳管、tracking 开启、存在未公开
   official revision、开放 incident 或 correction watch）；
2. 逐场重新核对来源证据：现有 official observation/revision 对照来源原文或新鲜 provider 响应，
   复核身份、终态和完整参赛名单；复核失败整场零写；
3. 生成 SHA 锁定的不可变候选包，dry-run 确认零写入；
4. 备份并取得人工批准后，事务内完成 status/result/publication；
5. 独立 verifier 逐场核对数据库与公网页面；
6. OperationLog 记录为人工修复；新链上线后由 standing policy 接管后续更正观察；
7. 对应 `provisional_overdue` incident 在业务闭环后解决。

这条路径优先用于当前 755/756/757，但代码不能硬编码 event ID；同形态停滞赛事复用同一流程。
修复窗口内必须确认没有自动化任务触碰目标赛事。

修复命令复用标准链路（当前 policy、共享 admission、reconcile、标准 result writer），
不再假设旧 revision 可直接公开；stale-digest enrollment 会先按当前 policy 轮换
（route 身份不变、source 重新过 admission、rotate 走既有 manifest 机制并留审计）。
其独立性体现在：独立命令、独立 SHA 锁定候选包、独立小型 G2 发布包，可在自动化链
全量灰度之前单独交付（独立 G2/G3）；执行窗口要求相关运行时开关开启，并先只读核对
每场 `observation.source_identity_id == enrollment.source_identity_id`，不成立时停止。

## 9. 更正链路

更正沿用 immutable revision：

- 内容未变：只推进 checkpoint，revision/publication 数不变；
- 内容变化且有合法 correction marker：创建新 revision，`supersedes` 指向旧 current；
- 内容变化但没有 marker：创建 conflict incident，不公开；
- 低优先级来源不能覆盖当前高优先级正式赛果；
- 公共页面仍显示统一“赛果”，不显示内部阶段。

生产不注入假赛果。更正写入通过隔离 PostgreSQL 测试和基于生产结构的匿名 fixture 验收。

## 10. 告警与审计

扩展 `audit_race_data_sync`，输出：

- 盘点分类与 reason-code 明细；
- identity discovery 守恒统计由 discovery 任务自身返回 payload 承载（审计不重复触网重放）；
- lifecycle admission 类型与冲突；
- 已到 T/T+30 但未推进的事件；
- 已有 official revision 但未 publication 的事件；
- correction watch 状态；
- task/claim/checkpoint、queue、capacity 和 free disk；
- `would_write=false`。

复用 `RaceLiveAlertIncident`：

- P0：跨 event、错误/部分赛果公开、人工锁覆盖、双 lifecycle authority；
- P1：来源终态后 10 分钟未公开、T+30 无状态推进、队列无消费者；
- P2：等待来源开放、单 provider circuit、route 即将过期。

P2 中的 `awaiting_source_window` 只进入统计，不产生高频通知。

## 11. 并发与事务

继续使用现有锁顺序：

```text
lifecycle registry barrier（仅 legacy 路径）
-> lifecycle control
-> event
-> projection control
-> tracking/checkpoint
-> source identity
-> observation/revision/result
```

data-sync admission 不新增另一把全局锁。reconciliation 与 discovery 按 event ID 升序、小批量执行。

必须在 PostgreSQL 16 验证：

- discovery 与 lifecycle reconciliation 并发；
- 两个来源对同一赛事的并发授予竞争（必须只有一条 enrollment 生效）；
- schedule 更新与 lifecycle 推进并发；
- lifecycle 推进与 result publication 并发；
- correction 与重复 provider task 并发；
- kill switch 在事务中途关闭；
- legacy membership 与 data-sync admission 同时出现。

所有情况要求无死锁、无重复 transition/revision/publication、无部分提交。

## 12. 配置与发布

继续使用现有 `RACE_DATA_SYNC_*` 开关，不新增第二套业务总开关。standing policy v2 会产生新的文件 SHA，发布包必须精确绑定：

- commit / image；
- policy 路径、原始文件 SHA 和 canonical digest；
- provider/reference registry SHA；
- migration leaf；
- Compose 服务和队列；
- 备份与回滚点。

预计没有 migration。如果最终 diff 出现 migration，必须停止并重新审查迁移、旧镜像兼容和回滚方案。

## 13. 性能预算

- future census：未来 30 天，按数据库条件筛选，不扫全部历史赛事；
- identity discovery：沿用每轮最多 3 个来源请求，并按地区/日期公平轮转；
- enrollment/lifecycle reconciliation：单批最多 20；
- lifecycle 和 selector：单批最多 100；
- racecard/result 继续共享 provider + region + date snapshot；
- 不增加普通 worker concurrency；
- 不改变 Web 1 worker × 4 threads；
- 不消费 `race_live`。

## 14. 回滚设计

优先行为回滚：

1. 关闭 correction；
2. 关闭 result public/apply；
3. 关闭 lifecycle apply；
4. 关闭 racecard/schedule apply；
5. 关闭 network、future discovery 和 scheduler；
6. 停专用 worker。

关闭后保留 observation、revision、transition 和 enrollment 审计，不清 Redis，不反向批改赛事状态。

代码回滚只恢复精确旧 image；policy v2 文件与 v1 文件分别保留，不能用同一路径静默替换。数据库损坏才使用验证过的 custom-format 备份恢复，并需要独立高影响授权。

## 15. 为什么这是最小可行方案

- 不建第二套赛事表、赛果表或状态机；
- 不新增 provider 和网络范围；
- 不新增公开页面；
- 预计不新增 migration；
- 只修正两个真实断点，并让三条授权路径共用一个判断；
- 可以先在 755/756/757 审计修复包和一场新未来赛事自然闭环上验证，再扩大到全部自动合格赛事。
