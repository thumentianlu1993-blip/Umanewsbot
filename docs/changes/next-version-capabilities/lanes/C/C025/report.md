# C-025：PR238 PostgreSQL 测试线程连接清理修复

任务：`C025-PR238-DB-TEARDOWN-FIX-001`。已完成实现及本地诊断验证，待 ROOT 安排原 R 上下文独立 review；尚未 push、更新 PR、执行正式 full、合并或发布。C024 ORM loader 计划及旧 worktree 保留，本轮没有启动其实现。

## 固定来源与范围

- 候选来源：`3b20813f6218a9076cd8e5f8aed352786c656560`。
- 原失败 merge：`e36d17290eb677881cbf7f2c3c4c32a36fc88d57`，tree `b59c56b8849b7c3d95d387277e7878dae2d3ab1e`；候选与 merge 文件内容相同。
- RED：`fb7b5a630831764bb7b8ff8d00256db16e43d855`，仅先增加会话关闭回归断言和测试设计。
- GREEN 代码：`f73970f017aa0a4834f0c1eca4387bcb990f8c91`，tree `db3d1bc2fdb2c6262aad5e233750e85b785148bf`。
- 独立 worktree：`/Users/mentianlu/.codex/worktrees/c025-db-teardown-fix/umanews`，分支 `codex/c025-db-teardown-fix`。
- 修复仅涉及 `server/stable/test_race_series_identity_2026_review_postgres.py` 和 `server/stable/test_racing_api_horse_staging_postgresql.py`。runner、worker、容器 entrypoint、业务服务、模型、迁移与配置均未修改；原 canonical test method 集合不变，没有新增 skip。
- 当前授权覆盖此纯技术修复；人工门禁统一引用根 `AGENTS.md`。本轮不操作共享主线、生产或外部业务发送。

## 根因与修复

PR238 的 run `37266491076` 中，031/032 分片分别完成 188/184 项业务测试并显示 OK，随后 Django 删除 `test_bounded_ci` 时遇到其他 PostgreSQL 会话。线程原先在 `finally` 调用 `close_old_connections()`，健康且未过期的线程自有连接会保留；项目默认连接寿命为 60 秒，主线程 teardown 无法关闭其他线程的 Django wrapper。

三个 worker 的 `finally` 改为在线程自身调用 `connections.close_all()`：identity apply、repeatable-read export、horse staging apply。保留线程入口的旧连接清理，保留业务并发与成功/失败、applied/replayed 断言。

回归先在线程业务调用前记录 `pg_backend_pid()`，join 后只查询这些 PID 是否仍在 `pg_stat_activity`；最多等待正常断开传播 2 秒，没有终止会话。GREEN 的成功日志不会列出 PID 数字，证据是绑定 PID 的断言实际执行并通过，不能据此编造成功 PID 台账。

## 实际验证

| 验证 | 固定代码 | 实际结果 |
|---|---|---|
| 最小 RED 三方法 | fb7b5a6 | 日志 Ran 3，3 个会话仍存活断言失败，随后 DROP 测试库失败 |
| 最小 GREEN 三方法 | f73970f | 3 项通过；0 failure/error/skip；lifecycle complete，exit 0，测试库清理成功 |
| 原分片 031 全部 canonical IDs | f73970f | 188 项通过；0 failure/error/skip；完整 teardown 成功 |
| 原分片 032 全部 canonical IDs | f73970f | 184 项通过；0 failure/error/skip；完整 teardown 成功 |

RED 日志中观测到 identity apply PID 69、export PID 72、horse PID 75/77 的 idle 会话。RED worker JSON 因 teardown 异常记录 infrastructure error，未导出三条 assertion failure；三条真实 RED 以 `.log` 为证，不将 JSON 误称为三条 failures。

相关验证共 372 项，ID **多重集合**与原计划完全相同、无重复。Django 会按 class 重排执行顺序；初次本地检查器使用列表顺序相等导致检查器拒绝，已改为多重集合校验，无测试失败、无代码修改或重跑。

使用原标准 `scripts/run_test_plan.py --batch` 顺序运行，每次一个容器。环境为 CPython 3.12.3、Django 5.2.1、PostgreSQL 16.15。本地缓存镜像为 `sha256:ab8494e6202dced04a6c2b5b885b3d1f2d9c80776ec8ae8d97f3552aae6b3ecc`，与原 CI 镜像 `sha256:9a908aa8567ef088d1caf431c1fc94b661d72839854e247ffd78d40b32aa3c62` 不同；没有 pull/build。这是本地诊断证据，不替代 ROOT 的 6530 项正式 full 或 GitHub 重跑。

首次 RED 启动因 macOS 默认 `/var/folders` 临时源目录不在 Colima 共享范围而失败，尚未执行测试，不计 RED。恢复仅将 TMPDIR 绑定到任务 runtime；标准 runner、安全隔离及权限均未放宽。

## 资源、证据与交接

ROOT 分配窗口为 2026-10-05 13:39:06–14:24:06 Asia/Shanghai，最多 1 容器、2 CPU、4 GiB、256 PID。daemon ID `22415fe2-f564-4c6c-9d80-987ba5b14450`。仅使用任务私有 DOCKER_CONFIG/context，未切换用户默认 context。容器 network none，只有内部 PostgreSQL loopback；实际隔离报告显示外网 Python/curl、嵌套 Docker 均 blocked。031/032 的 inspect 留存了只读 rootfs、cap-drop ALL、no-new-privileges 和资源限制。

测试结束后自有容器均由标准 runner 自动移除；最后核对运行容器为 0，仅保留其他任务原有 exited 容器。没有人为杀 PostgreSQL 会话。额度前后均为 used 70%；没有触及 used 72% 或 45 分钟停止条件。共享资源分配状态由 ROOT 释放，C 不修改 dispatch_state。

原始失败证据：`/Users/mentianlu/.codex/runtime/fourth-integration-evidence/ci-failed-37266491076`，保持不变。
本轮证据：`/Users/mentianlu/.codex/runtime/c025-pr238-db-teardown-fix-001`。

- `original-failure-hashes.json`：原 031/032 JSON/log 与 execution-plan 的 SHA256。
- `red-pg16/`、`green-pg16/`、`related-031/`、`related-032/`：原始 JSON/log/执行计划。
- `related-summary.json`：372 项汇总及 canonical ID 校验。
- `related-031-container-inspect.json`、`related-032-container-inspect.json`：实际运行容器限制。
- `red-mount-setup-failure/`：首次挂载启动失败，单独保留。
- `static-checks.json`、`candidate.diff`：测试方法集合与 runner 不变的静态证据。
- `handoff-receipt.json`、`artifact-index.json`：报告提交后的 HEAD/tree/parent、报告及证据哈希。

下一步由 ROOT 在原 R review 上下文审查；技术 finding 按批准范围修复并复验。正式 full、PR 接线与交付由 ROOT 统一协调。
