# rollout：2026 赛历赛事中文展示名补齐

## 对既有任务/worktree 的影响

- 与 `remove-handicap-markers-from-race-names`（已完成 2026-07-22）正交互补：本 change 新写入的中文名同样遵守让赛标记不进展示名规则；两个 change 写入对象集不重叠（去让赛只动已含中文名的对象，本 change 只动原文回退对象）。
- 与 2026 赛历/历史系列双卡片问题（未立项）相邻：本 change 不写 `RaceSeries`，避免与该案冲突；双卡片案将来合并系列时，本批事件级中文名不受影响。
- worktree：`.worktrees/translate-2026-race-names`，分支 `codex/translate-2026-race-display-names`（基于 origin/main `559cec7a`）。

## 生效边界

- 唯一写入：生产 `RaceEvent.chinese_name`，573 场 2026 已发布赛事，用户审核通过行。
- 无迁移、无配置变更、无新依赖；部署仅在代码合入 main 后走标准 `deploy_lowcost.sh`。

## 安全检查点

1. 方案审核（plan-eng-review 等价）通过前不进入实现。
3. 写入前：备份 SHA + `pg_restore -l`；artifact SHA 与授权信息作为 commit 强制参数。
4. 漂移即整批回滚；写入后立即 --verify 与前台抽检。

## 恢复 handoff

- 写前 custom-format 备份路径与 SHA 记录于 release_report；回滚入口 `deploy/restore_db.sh <backup>` 或按 OperationLog before 快照反向受控写回（需另授权）。

## 发布状态

- 2026-07-22：change 建立（spec/design/test_cases/tasks/rollout）；方案审核首轮 REVISE（1 high + 3 medium + 7 low）→ 全部修订 → 同一 reviewer 限定复审 **APPROVED**（残余 4 项 low 文档一致性瑕疵已顺手修订）。待用户确认方案后进入测试先行与实现。
