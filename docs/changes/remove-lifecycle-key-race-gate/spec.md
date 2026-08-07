# 移除 lifecycle 重点赛事资格门禁规格

## 1. 目标

赛事生命周期是赛事本身的基础能力，不应由运营优先级决定。本 change 移除 strict v2
首次纳管中的 `RaceEvent.is_key_race=true` 硬门禁，使明确 manifest 选中的普通赛事也能进入
shadow lifecycle。

`priority`、`is_featured` 和派生的 `is_key_race` 继续作为运营、展示和审计信息保存，但不再
决定赛事能否根据日期和时间推进状态。

## 2. 纳管资格

明确选中的赛事仍必须满足：

1. event ID 存在、为正整数、无重复，单批 1–20 场；
2. `visibility_status=published`；
3. `status=scheduled`；
4. 地区、IANA 时区、美国逐场 allowlist、日期和 aware `race_datetime` 符合既有合同；
5. `manual_lock_flags` 为空；
6. control 不存在，或属于同一 manifest 的精确 replay；
7. strict v2 manifest 的 SHA、commit、有效期和数据库快照全部匹配。

赛事可以是 P0、P1、P2、featured 或非 featured；`is_key_race=false` 不再导致 prepare、
dry-run 或 apply 失败。

## 3. 范围

- 修改 strict v2 enrollment 的资格判断；
- 增加非重点赛事 prepare、dry-run、apply 和混合批次原子性的测试；
- 更新纳管、观察和生产文档；
- 不修改模型、migration、状态机、Beat 周期或 Celery 路由。

## 4. 非目标

- 不自动给数据库全部赛事创建 control；首次纳管仍必须使用明确 ID 的 strict manifest；
- 不恢复或放宽 v1 `--apply`；
- 不允许 `--auto-discover` 进入 strict v2 apply；
- 不修改赛事 `priority`、`is_featured` 或公开展示；
- 不在本 change 内开启 enforce；
- 不新增 provider、赛前资料、新闻联动或赛果同步。

## 5. 验收标准

- `is_key_race=false` 的合法赛事可以生成 strict v2 manifest 并创建 shadow control；
- P0/P1/P2 混合批次整批成功，control 集合与 manifest 精确一致；
- 未发布、非 scheduled、取消、未知地区、错误时区、美国空 allowlist、无日期、manual lock
  等既有硬门禁保持不变；
- manifest 仍冻结 `priority/is_featured/eligibility.is_key_race` 作为审计快照，字段漂移仍拒绝；
- `false/off` apply、shadow-only、单事务、最多 20 场、replay 和零公开状态写入合同保持不变。


代码发布、生产只读 prepare/dry-run、`false/off` control apply、`true/shadow` 启用仍是四个
独立停点，分别使用当前步骤的新授权。任何较早授权不得跨越代码 review 后的发布门禁。

用户决定把 shadow 决策窗口设为 24–48 小时，以尽快判断是否准备 enforce；该窗口只证明其中
真实到期并跨过 T/T+30 的代表性赛事。未在窗口内跨越自身边界的赛事必须明确标为“尚未生产
观察”，不得计入逐场时序通过数；enforce 仍是独立 change、独立 review 和独立授权。
