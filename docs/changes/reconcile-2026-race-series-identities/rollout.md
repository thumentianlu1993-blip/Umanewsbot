# rollout：2026 赛事系列身份归并与双卡片治理

## 工作区与基线

- worktree：`/Users/mentianlu/Code/umanews/.worktrees/reconcile-2026-race-series-identities`
- branch：`codex/reconcile-2026-race-series-identities`
- 起始基线：`origin/main@f0d3fbd6e71374b425e3bbae2041d47758270546`

主仓库和既有翻译/evidence worktree 不参与本任务修改。

## 与既有任务的关系

- 复用已上线的 `race_series_identity_review`，不修改已完成的 573 场赛事中文名。
- 系列归并后 event 的 `chinese_name`、slug 和公开状态保持不变；后续系列术语同步以本任务的正式
  系列身份为前置。
- 与历史批次 runner、准实时赛果和 P0 马资料共享 `RaceEvent/RaceSeries`，但本任务不修改赛事详情、
  participant/result 或调度开关。apply 前必须确认没有活跃的同范围系列写入任务。

## 阶段边界

1. 规划：五文档和方案审核，不写业务代码。
2. 实现：只新增审核适配层和测试，不访问生产。
3. 只读生产审核包：部署工具后生成候选，不写数据库。
4. 用户审核：工作簿定稿，不等于 apply 授权。
5. 数据发布：新 review、备份和精确授权后，复用既有引擎 apply/verify。
6. evidence-only 收尾：只记录已发生事实。

## 灰度策略

- 审核范围完整覆盖正式快照中的全部未关联 2026 targets。
- 首批写入只覆盖用户批准且 `engine_compatible=true` 的互斥动作；不以地区或行数配额强行凑批。
- 首批所有批准动作使用一个互斥 manifest 和一个数据库事务，不拆 shard；动作量本身不能成为临时
  改变原子性语义的理由。若后续实测证明单批不可接受，先停止并另行修改方案、复审和授权。
- `keep_independent/ignore_false_match` 可与正向动作同批，但同一系列对/事件出现冲突决定时整批拒绝。

## 生产检查点

- P0：正式快照和工作簿完成，数据库零写入。
- P1：用户定稿 + decisions + prepared verifier 完成，数据库仍零写入。
- P2：备份完成且恢复清单可读，尚未 commit。
- P3：首批单一 manifest commit + verifier + 页面验收完成。
- P4：未处理总账另行留档。

## 回滚

- 首批事务失败且未提交：无需业务回滚，记录失败证据。
- 首批已提交后验收失败：优先使用既有 rollback ledger 精确回滚；发现 ledger 或当前状态漂移则停止，转数据库
  备份恢复评估并重新授权。
- 回滚不得删除其他任务新增的系列、赛事或关系；verifier 只约束本 manifest scope 和守恒指标。

## 当前状态

- 已完成仓库和生产只读探索；没有创建候选 artifact、没有修改代码、没有生产写入。
- 当前进入 spec/design 方案审核前阶段。
