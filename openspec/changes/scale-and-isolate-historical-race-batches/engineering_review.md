# 工程评审记录

评审时间：`2026-07-14T12:08:26+08:00`
评审模式：Full（profile 默认按 `feature`）
评审轮次：2
结论：APPROVED

## What Already Exists

- `HistoricalRaceEventTarget`、正式总账状态机、按 target 行锁的日期/来源/详情 importer，以及 SHA/approval/备份门禁。
- `historical_race_batches.py` 的地区选择、100 场领先护栏、已耗尽地区退出比较、不可变 exclusion snapshot 和确定性 artifact。
- `orchestrate_race_event_crawl` 的 plan/run state、prepare/audit/dry-run/apply-check 和 resume 产物模式。
- `TermGateReprocessLock`、`MultiregionAttributionLock` 的数据库租约/heartbeat 字段，可复用其事务获取模式。
- 现有 Docker 镜像 revision label、原生 `docker run --rm` 历史批次经验、数据库备份和生产健康门禁。

## Round 1 Findings

1. `F-001` 严重：宿主 `runtime` 挂到 `/app/runtime` 会遮住镜像内工具，固定镜像不能证明固定代码。已改为 artifact 挂载 `/app/historical-runtime`，工具只从镜像内只读路径及 tool manifest 执行。
2. `F-002` 严重：普通 deploy 仍会通过 Compose 处理 DB/Redis 和 orphan，违反 runner 隔离。已拆分为 `--no-deps` 应用更新与显式 infrastructure bootstrap。
3. `F-003` 高：checkpoint、日志、owner token 和父子进程退出边界不够精确。已补 8 KiB 脱敏摘要、完整文件日志、fsync+rename、token hash、进程组清理和锁释放顺序。
4. `F-004` 中：tasks 缺少可量化 TDD 假设。已新增批次、并发租约、权限隔离、资源与日志 PASS/BLOCKER 门槛。
5. `F-005` 高：接管和 step 审计若只塞入 run JSON 会无界增长且并发更新困难。已新增 append-only `HistoricalBatchRunEvent`，control role 只获三张控制表权限。

## Round 2 Findings

6. `F-006` 高：首次部署时 runner 表尚不存在，数据库 preflight 会形成循环依赖。已增加仅首次可用的 host-only 无痕迹门禁，任何 runner 容器/网络/secret/同名表存在即拒绝 bypass。
7. `F-007` 高：租约过期不足以证明旧 apply 已停止。已要求 runner 连接设置可识别 `application_name`，接管前通过 `pg_stat_activity` 证明无活动连接/事务，且先等待整个子进程组退出。

第二轮复核修改后的 design、runner spec 和 tasks，没有发现新的未解决问题。

## NOT in Scope

- 赛事身份、中文译名、来源优先级和待审 gap 产品结论：继续使用已经批准的正式总账。
- 自动公开和前台交互：历史赛事继续 draft，公开开关保持关闭。
- Celery Beat 自动调度：runner 只执行显式批次 plan，不建设永久循环。
- 重写现有日期、来源和详情 importer：runner 只包装并强化已有门禁。

## Failure Modes

| 路径 | 现实故障 | 测试 | 处理与信号 |
| --- | --- | --- | --- |
| 批次选择 | 选择使用 250、artifact 仍按 50 校验 | 上限一致性回归 | 写 artifact 前 fail closed，summary 指出差异 |
| 双锁 | 两个容器同时抢占 | PostgreSQL 20 并发测试 | 唯一租约 + 文件锁，第二个明确失败 |
| 心跳 | runner 活着但 DB 短暂抖动 | fake clock/租约测试 | 不进入下一 step；过期后仍需容器和事务核验 |
| checkpoint | state 原子写前掉电 | 文件故障注入 | DB/file 分叉 blocked，不静默跳过 |
| crawl 权限 | 抓取代码误写业务表 | PostgreSQL role smoke | 数据库拒绝并标记 step failed |
| apply 网络 | importer 隐式访问公网 | internal network smoke | 网络失败，不临时开网重试 |
| 普通部署 | `--remove-orphans` 或依赖启动影响 runner/DB | shell 契约 + 生产演练 | `--no-deps` 应用更新，基础设施缺失即停止 |
| 首次迁移 | 新表不存在无法查询状态 | host-only preflight 测试 | 仅无 runner 痕迹时允许首次建表 |
| 退出/接管 | 父进程退出但子命令仍写库 | 进程组测试 + pg activity smoke | 子进程退出前不释放锁，接管前查活动事务 |

## Completion Summary

```text
Plan Engineering Review Summary
================================
Review rounds: 2 (converged at round 2)

Step 0: Scope Challenge — accepted with deployment lifecycle reduced to separate runner scripts
Architecture Review: 5 issues found and resolved
Code Quality Review: 1 issue found and resolved
Test Review: 1 gap identified and resolved
Performance Review: 0 unresolved issues
Consistency check: proposal/design/specs/tasks consistent

What already exists: historical ledger/importers, batch guard, orchestration state, DB lease patterns
NOT in scope: identity/source/public UI/Celery automation
Failure modes: 0 critical gaps remaining

Next: Ready for complete test-case specification, then implementation.
```

## 实现后代码复审

- Round 1：修复子进程 stdout/stderr 无界内存累积、失败状态缺少脱敏诊断、takeover 可指定任意 checkpoint 三项问题。
- Round 2：修复首次文件锁打开/抢占/审计失败后数据库租约和 run 状态仍停留在 running；同 owner 重复启动继续保持原 run 不被误判失败。
- Round 3：补充 PostgreSQL trigger，禁止 historical runner 删除 `RaceEvent`，并增加真实 PostgreSQL 回归。
- Round 4：修复 crawl prepare 在最小权限 control role 下误写业务 `TaskExecutionLog`；新增宿主 takeover 探针，实际核验旧容器不存在并只读挂载固定 checkpoint。
- Round 5：复核模型约束、双锁、心跳、恢复、命令 allowlist、数据库 trigger、Docker 网络/资源、部署与回滚脚本，没有发现新的 actionable finding。

最终验证：runner 聚焦 52 项、runner+历史批次 118 项、加历史网络日志组合 122 项、完整 `stable` 1350 项通过（跳过 7）；真实 PostgreSQL 6 项、Django check、migration drift、shell/diff、OpenSpec strict/all 均通过。
