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

最终验证：runner 聚焦 52 项、runner+历史批次 118 项、加历史网络日志组合 122 项；合并最新主线后的交叉组合 194 项通过（跳过 1），完整 `stable` 1386 项通过（跳过 7）。真实 PostgreSQL 6 项、Django check、migration drift、shell/diff、OpenSpec strict/all 均通过。

## 生产 smoke 后资源门禁增补评审

评审时间：`2026-07-14T19:40:00+08:00`
评审模式：Full（`.openspec.yaml` 未声明 profile，按 `feature`）
结论：APPROVED

生产 runner smoke 证明了网络和数据库权限隔离，但正式 batch006 启动前发现 runner 的直接 `python_tool` 子进程没有继承编排服务已有的请求预算和 source-cache 环境。若不修复，底层工具会把缺失的请求上限解释为无限，并且宿主 env 可以把 5 GiB 磁盘底线调低。

本轮工程评审形成并解决 `F-008`：仅在 `historical_runner.sh` 校验数值仍可被直接调用 Django 管理命令绕过。最终设计采用三层约束：宿主脚本校验数值并检查实时磁盘、Django 服务重复校验 settings 和磁盘、crawl 父进程覆盖所有子进程的共享预算账本/cache 路径与上限。请求间隔固定至少 1 秒。改动不触及赛事身份、selection、importer、公开状态、数据库结构或其他 phase。

评审确认新增测试覆盖恶意宿主环境、同 run 多 step 共享账本、异常 settings 直调旁路、磁盘不足、脚本上下边界及 verify/apply 不受影响。不存在未解决架构、迁移、性能或产品交互问题，可以进入测试优先实现。

实现后第二轮复审发现并解决 `F-009`：请求账本路径虽已固定，但未进入 runner checkpoint，暂停期间删除或改小账本会重置整批累计额度。设计补充为 checkpoint 顶层保存请求账本和 cache manifest 的存在状态、大小、SHA；completed、resume 和下一 step 前均核验，任何创建、删除或修改都转 blocked。该补充不改变 plan schema、旧 checkpoint 读取或赛事业务数据。

第三轮复审发现并解决 `F-010`：`Path.is_file()` 会跟随 symlink，且升级前的非终态 checkpoint 没有资源身份。最终约束为资源账本固定路径在任何读取前拒绝 symlink/非普通文件；旧 completed checkpoint 只读兼容，旧 paused/failed/planned crawl 不得继续执行，必须 blocked 并保留现场。

第四轮复审发现并解决 `F-011`：镜像内任意 SHA 匹配的 Python 工具都能进入 crawl，其中术语清理脚本可直接联网且不消费赛事预算。生产 `/app/runtime/tools` 改为显式赛事 runner 白名单；离线测试临时工具根仍可注入，生产新增工具必须经过代码、测试和新固定镜像。

第五轮复审发现并解决 `F-012`：允许的 `orchestrate_race_event_crawl` 会由 `AdapterRunner` 再覆盖父级请求账本、cache 路径和请求间隔。嵌套 adapter 改为继承父级固定路径，并对 policy 只允许收紧：请求/cache 取较小值，间隔/磁盘底线取较大值；普通非 runner 编排仍使用自身 run 目录。

第六轮复审发现并解决 `F-013`：资源身份只在 step 成功后写 checkpoint，首个 crawl step 消耗请求后失败时仍可在恢复前删除账本并重置累计额度。runner 现于取得双锁后先保存资源基线；任何已启动 step 的可控失败在释放锁前刷新失败时资源身份，异常强杀未执行收尾时则由基线与磁盘漂移阻断恢复。

第七轮复审重新核对宿主与应用双层资源校验、共享账本、失败/强杀恢复、工具白名单、嵌套 AdapterRunner、数据库与文件 checkpoint 原子性及非 crawl 兼容路径，没有发现新的 actionable finding。runner 聚焦 `64/64`、historical 组合 `200/200`、补丁完整 `stable 1399/1399` 通过；两次合入最新多地区归属主线后，最终交叉专项 `208/208`（跳过 1）、完整 `stable 1417/1417` 通过（跳过 7 个既有环境专项），最终 AMD64 镜像内 runtime 专项 `239/239` 通过（跳过 1）。Django check、migration drift、shell、diff 和 OpenSpec strict/all 通过。
