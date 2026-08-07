# `prepare-lifecycle-shadow-enrollment` 实现交接

## 1. 从这里开始

这是 Codex 原生 change，不使用 旧规格流程。先读同目录：

1. `spec.md`
2. `design.md`
3. `test_cases.md`
4. `tasks.md`
5. `rollout.md`

再读仓库根 `AGENTS.md`、`docs/codex_workflow.md` 和 session bootstrap 要求的状态文档。

## 2. 当前基线与授权

- 设计 worktree：
  `/Users/mentianlu/Code/umanews/.worktrees/prepare-lifecycle-shadow-enrollment`
- 分支：`codex/prepare-lifecycle-shadow-enrollment`
- 设计基线：`origin/main@43b81fd3288a1e7b997ffad78d03565327e3d990`
- 用户已明确回复“G1 范围确认”，测试先行与本地实现已获授权并完成。
- 仍未授权 commit/push/PR、联网、生产写入、部署、control apply 或开关变更。
- 当前门禁为独立代码 review；通过后冻结 fingerprint 并停止等待发布 Git 动作授权。

## 3. 根因

阶段 A 执行器已部署但关闭。现有 reconcile apply 依赖人工准备 manifest；manifest dry-run
只读取 ID，没有执行与 apply 相同的完整 schema、美国时区、冻结资格和 schedule 门禁。
apply 又会信任冻结 eligibility，而不对当前 DB 做完整 CAS，可能产生 dry-run/apply 结论差异
或把已漂移赛事纳管。旧 v1 apply 还能绕过 v2 的 shadow-only/≤20/整批事务门禁；v2 apply
如果不硬校验 `false/off`，新 control 也可能在 verify 前被既有 scanner claim。生产当前
0 control、0 race_datetime，不能直接打开 shadow。

## 4. 必须复用

- `server/stable/services/race_event_lifecycle.py`
- `server/stable/management/commands/reconcile_race_event_lifecycle_controls.py`
- `server/stable/tasks.py` 的两个 lifecycle task
- `RaceEventLifecycleControl` / `RaceEventLifecycleTransition`
- 既有生命周期 SQLite/PostgreSQL 测试

禁止新建第二状态机、control 表、调度器或 provider 链。

## 5. 推荐实现文件

新增：

- `server/stable/services/race_event_lifecycle_enrollment.py`
- `server/stable/management/commands/prepare_race_event_lifecycle_enrollment.py`
- 可新增独立测试文件，避免继续膨胀旧 1000 行测试文件。

修改：

- `server/stable/management/commands/reconcile_race_event_lifecycle_controls.py`
- 必要时小幅修改 `race_event_lifecycle.py`，但纯决策语义不得分叉；
- 状态/运维文档。

不应新增 migration、Beat entry、settings 或 Compose 开关。

## 6. 实施顺序

1. 测试 subagent（用户授权后才可启动）按 `test_cases.md` 写真实 RED；
2. 主线程确认 RED 原因；
3. 按文件边界委派实现；
4. SQLite 聚焦与回归；
5. 隔离 PostgreSQL 原子/并发测试；
6. Django/migration/diff/query checks；
7. 未参与实现的独立 reviewer；
8. 修复 finding 并复用 reviewer 会话；
9. 冻结 fingerprint，停止等待 commit/push/PR 授权。

## 7. 不可妥协的合同

- prepare 明确 IDs、≤20、shadow-only；
- v2 dry-run/apply 同 loader、同 preflight；
- v1 永久 dry-run-only；任何 v1 apply 零写拒绝；
- v2 apply 只接受严格 false/off，且生产需核对 Beat/worker 同配置、零 active/claim；
- apply 单事务、排序锁、完整 DB CAS；
- 不同 manifest existing control 拒绝；
- 相同 manifest 精确 replay；
- 错误时区不修正，只拒绝；
- `local_start_time` 不推导 `race_datetime`；
- 功能启用是 control apply 之后的另一授权；
- 当前生产只能证明无时间路径，不能宣称 running/T+30 已线上验证。
