# 移除 lifecycle 重点赛事资格门禁设计

## 1. 根因

`_validate_enrollment_eligibility()` 当前把 `event.is_key_race` 与发布状态、生命周期状态、
时区和人工锁放在同一组硬门禁中。该判断把运营优先级错误地提升成生命周期正确性的前置条件，
导致系统内合法的 P2 或非 featured 赛事即使已有可信 `race_datetime` 也不能纳管。

## 2. 修改方案

只移除 `_validate_enrollment_eligibility()` 对 `event.is_key_race` 的拒绝。其余校验、strict v2
schema、prepare/preflight/apply 共用路径及数据库事务不变。

manifest 继续冻结：

- `priority`；
- `is_featured`；
- `eligibility.is_key_race`。

这些字段从“资格授权”降为“生成时审计快照”。apply 前仍通过既有 snapshot CAS 要求它们未
漂移，防止批准后赛事元数据改变；布尔值为 `false` 本身则是合法输入。

## 3. 数据流

```text
明确的 1–20 个赛事 ID
  -> 校验赛事存在、published、scheduled、地区/时区/日期和人工锁
  -> 冻结 priority/featured/is_key_race（只审计，不筛选）
  -> strict v2 manifest
  -> dry-run
  -> false/off 下 atomic shadow-control apply
  -> true/shadow 观察
```

## 4. 并发、性能与兼容

- 不改变最多 20 场、排序加锁、单事务 bulk create 和 replay 语义；
- 不增加 scanner 查询，也不产生全表轮询；没有 control 的赛事不会被每五分钟扫描；
- v2 JSON 结构不变，因此不增加 schema version；旧 v2 manifest 中
  `eligibility.is_key_race=true` 继续有效；新 manifest 可以冻结 `false`；
- v1 apply 继续永久拒绝，旧 auto-discover 路径不作为生产纳管入口；
- 不新增 migration。若回滚到仍含重点赛事门禁的旧代码，先把全局开关恢复为严格
  `false/off`；已创建的非重点 control 不会因代码回滚自动失效，因此在受审的暂停、mode-off
  或其他处置完成前禁止重新开启 shadow/enforce。审计不得删除。

## 5. “所有赛事适用”与自动全量纳管的边界

本 change 解决资格问题：任何合法赛事均可被 strict manifest 纳管。它不把数据库中所有存量
或未来赛事自动创建 control。自动全量纳管需要另行设计日期窗口、历史排除、取消/草稿语义、
批量上限和新赛事触发点，避免一次性扫描全部历史总账；不得用本次小修隐式完成。

## 6. 生产观察证据

R1 必须为 16 场输出逐场审核表，至少包含 priority、featured、派生 `is_key_race`、地区、
local/UTC 时间、predicted decision、next refresh 和预期 proposal 边界，并硬性证明至少一场
`is_key_race=false`。当前目标集合预期包含 8 场 false，但以执行时数据库快照为准。

24–48 小时观察按“实际跨过边界的赛事”计数：逐场记录 scanner、T、T+30、proposal、重复数
和公开状态不变证据。8 月 8 日等尚未到期赛事只验证已纳管和未提前推进，不声称其 T/T+30
已经生产验证。
