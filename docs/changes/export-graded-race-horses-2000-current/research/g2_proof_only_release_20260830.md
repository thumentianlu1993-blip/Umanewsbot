# G2 候选：exclusive-account proof-only 最小代码发布

状态：`PROPOSED_NOT_APPROVED`。本页和相邻 JSON 只形成待批准候选，不授权 commit、push、merge、部署、
容器重启、TRA 请求或数据库写入。

## 结论

Montjeu N1 已有固定 seed、最多 16 GET、零数据库写入的 G3，但 production 当前 checkout
`bef0cdc5034bd2516df9876b2a7dde2357f03495` 不包含 Django exclusive-account proof generator。原
`g2_disabled_foundation_release_20260829.md` 同时携带 Ireland、staging、identity 和 migration
`0076–0079`，作为解除 N1 前置阻断的发布范围过大。

本候选从最新 `origin/main@409f2ac6cd15b7e8781dd9ada2903c91a9fc2121` 隔离，只加入三项运行文件和
两项测试文件。它不增加 model、migration、setting、常驻任务或网络入口；唯一生产能力是由 operator
显式运行只读管理命令，将本地 runner host、production host 两份 process evidence 与 production
settings/DB/Celery/Redis 现场证据合并为最长 15 分钟的 `0600` proof。

精确文件与 SHA 见
`research/g2_proof_only_release_proposal_20260830.json`，proposal SHA-256 为
`1a6884657639ecb2d42e0f791856b5436c83321b6c28264abf0c206eb59df37e`。候选 worktree：
`/Users/mentianlu/.codex/worktrees/tra-proof-only-g2-20260830`，保持 detached、未提交。

## Scope challenge 结果

### What already exists

- production 已有 `RaceEventLiveTracking`、`RaceEventLifecycleControl`、`ExternalDataImportLock`。
- production 已有 `RaceDataSyncFlags`、Celery inspector、Redis broker 和关闭态 flags。
- 当前本 change 已有 host collector、proof service/command 和离线测试。
- Montjeu runner、seed、account budget 和凭据留在本地受控 runner；本次不把完整 horse foundation 搬入
  production。

### 本候选包含

1. host `ps/docker ps/docker top` 只读 collector，分别生成 `runner` 与 `production` v2 evidence；只保存
   PID、marker、命令 SHA，不保存原命令。
2. Django proof service，核对 live/data-sync flags、DB claim/import lock、完整 Celery worker 快照和三个
   Redis queue。
3. 管理命令，只输出 status/scope/valid-until/proof SHA/`database_writes=0` 的脱敏摘要。
4. host 与 Django/management-command 聚焦测试。

### NOT in scope

- Ireland/model/staging/identity/schema migration：与生成 N1 proof 无关，留在原 foundation G2。
- Montjeu 或其他 TRA 网络请求：继续由已经批准的 N1 G3 单独控制。
- credential 持久化或向 production 传输：本候选不读取凭据。
- DB apply、发布、QQ/邮件、race-live/race-data-sync activation：全部排除。
- production 脏 checkout 清理：现有 deploy/QQ runtime 改动属于用户/运行态，不覆盖、不 reset。

## Architecture review

Round 1 发现两个 P1。第一项：proof service 原先引用 migration `0077` 才新增的
`ExternalDataSource.THE_RACING_API`，直接移植到当前 production 会 import 失败。已改为稳定 source key
常量 `the_racing_api` 查询 `ExternalDataImportLock`；数据库列本来是 `varchar(32)`，该只读查询在 migration
前后均合法，因此候选保持零 migration。

第二项：凭据与 N1 runner 位于本机，而 production 的常驻与临时 caller 位于服务器；单份 host evidence
不能同时排除两端 one-shot。collector schema 已升级为 v2 并绑定 `host_role`；Django command 强制接收
`runner` 与 `production` 两份 fresh evidence，hostname 必须不同，并把两端 matching process 一并计入
`other_backfill_processes`。production DB/Celery/Redis 继续核对常驻 caller。由此无需把 credential 复制到
服务器，也不把人工声明替代为机器证据。

其余约束通过：Django monolith 不变；无新依赖；无 settings/Compose/Nginx 变化；无 Celery task；proof
输出原子写入、目录与文件权限 fail closed；unknown/partial/nonzero runtime evidence 不生成 proof。

## Code quality review

- service 复用现有 models、`RaceDataSyncFlags`、Celery app 和 Redis URL，没有复制生产状态机。
- management command 不打印 credential alias、host evidence 内容、worker task 名或任何 secret。
- host collector 对命中进程只保存 marker 与完整命令 hash；原命令不进入 artifact。
- management-command 参数 plumbing 原先没有直接测试，已补充脱敏 stdout 与 worker 参数映射测试。
- 无新增包、环境变量、数据库索引或 query loop；数据库只执行三个 count query。

## Failure modes

| 场景 | 处理 | 测试/信号 |
| --- | --- | --- |
| 任一 host `ps`/Docker listing 失败 | 不生成可用 host evidence | collector 异常退出；operator 看到非零状态 |
| 任一端已有 TRA one-shot runner | evidence 保存 marker/hash，Django generator 拒绝 | matching-process test |
| runner/production evidence 缺失、角色错配或同一 hostname | generator fail closed | 双角色/不同 host test |
| host evidence 过期或 SHA/scope 漂移 | generator fail closed | stale/match test |
| Celery 无 reply、worker 集合变化或任务非空 | generator fail closed | 双 active/partial worker test |
| Redis queue 非零或不可达 | generator fail closed | service 明确异常；proof 文件不存在 |
| live/data-sync flag 或 DB claim/lock 非零 | generator fail closed | network-flag test 与 production 现场摘要 |
| 输出路径已存在、非私有目录或 symlink | 原子写入前拒绝 | service path/permission contract |
| 生产部署失败或 health 回退 | 切回前一 image/release，不运行 N1 | 既有 release/rollback runbook |

## Test review

- clean latest-main candidate：host collector `2/2`；Django service/command `6/6`。
- `manage.py check` 通过；`makemigrations --check --dry-run` 为 `No changes detected`。
- 三个运行文件 `py_compile` 通过；两个 production Compose 文件在临时空 `.env` 下 `config --quiet`
  通过；临时 `.env` 已删除。
- 原完整 worktree 相邻 account-budget/horse runner 合并为纯 Python `34/34`，证明 proof schema 的 consumer
  仍有独立覆盖；最小 Django 测试不再顶层依赖尚未发布的 account-budget 模块。
- latest-main 上 race-data pipeline、TRA source proof 与 deployment contract 相邻回归 `123/123`。

## Performance review

一次 proof 只执行：host/container process listing、固定三类 DB count、固定五次 Celery inspector 调用和
三个 Redis `LLEN`。无无界 DB scan、网络分页、重试循环或常驻调度。最长有效期 15 分钟，host evidence
最多 2 分钟；任何慢/partial 结果都停止，不用缓存旧值降级。

## 发布与回滚边界

G2 获准后仍须从 exact candidate 形成 commit/tree/image SHA，再次运行相同验证和只读安全检查。production
使用 isolated release，不在当前脏 checkout 原地覆盖；worker 有 active/reserved/scheduled task 或 broker
queue 非零时不重启。发布后先验证 migration leaf 未变化、web/worker revision、health/log，再现场生成
proof。部署成功不自动运行 N1；N1 仍只按既有 G3 的 seed/host/path/16 GET/零写合同执行。

回滚只切回发布前 image/release；没有 migration reverse 或数据恢复。回滚后 proof command 消失是预期，
任何已生成 proof 立即作废，不得复制到其他 run。

## Plan Engineering Review Summary

```text
Plan Engineering Review Summary
================================
Review rounds: 2 (converged at round 2)

Step 0: Scope Challenge — scope reduced to proof-only release
Architecture Review: 2 issues found and resolved
Code Quality Review: 1 issue found and resolved
Test Review: 1 gap identified and resolved
Performance Review: 0 issues found
Consistency check: candidate, tests, rollout and runbook aligned

What already exists: production runtime state models/flags/Celery/Redis; local collector/generator
NOT in scope: migrations, horse foundation, TRA calls, business writes, activation/publication
Failure modes: 9 fail-closed paths reviewed; 0 critical silent gaps

Next: exact G2 approval is required before commit/push/merge/deploy.
```

Round 2 只重读上述修改与直接依赖，未发现新的 P0/P1/P2；本 legacy change 无 `.sidecar` 或
`.openspec.yaml`，按技能约定不创建或伪造 OpenSpec ledger/state。
