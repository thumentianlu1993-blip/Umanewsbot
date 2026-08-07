# 新 Session 启动模板

## 唯一门禁来源

仓库根 `AGENTS.md` 是全部任务、代理和 worktree 的唯一人工确认门禁来源。本文件不定义人工确认门禁；
遇到授权、确认、合并、发布、生产写入或外部发送问题时，直接按根文件的 G1/G2/G3 判断。

## 启动读取

每个 session 先读：

1. `AGENTS.md`
2. 本文件
3. 按本次任务关键词查询 `docs/current_state.md` 和 `docs/decisions.md`
4. 按任务影响补读 `docs/project_overview.md`、`docs/project_status.md` 或相关 `docs/changes/<slug>/`

部署、回滚、生产数据或运维任务再读相关章节：

- `docs/deploy_runbook.md`
- `docs/deploy_production.md`
- `docs/alicloud_hongkong_step_by_step.md`
- `docs/rollback_guide.md`
- `docs/backup_recovery.md`

不要求每次无差别加载全部历史文档；`docs/current_state.md` 与摘要冲突时，以前者为准。

## 开始前必须明确

- 当前项目与本次任务目标；
- 当前分支、worktree、脏改动和并行任务；
- 仓库预期与可证明的当前运行态；
- 修改范围、非目标、验证方式和已知阻塞；
- 根 `AGENTS.md` 的 G1/G2/G3 是否被触发，以及现有用户指令是否已经覆盖。

这是一项代理内部检查，不需要机械地要求用户确认。只有根 `AGENTS.md` 所列条件实际触发时才停下。

## 推荐启动提示词

```text
请先阅读根 AGENTS.md 和 docs/session_bootstrap.md，并按任务关键词查询 current_state、decisions
及相关运行手册。确认当前 worktree、并行任务和真实运行态后，用自己的话总结目标、范围、阻塞、
验证方式，以及 G1/G2/G3 的适用情况。可从仓库确定的事实请自行检查，不要重复询问；人工确认
只按根 AGENTS.md 执行。
```
