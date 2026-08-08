# 生产 migration history 一致性修复 Rollout

## 1. 基线

- worktree：`/Users/mentianlu/.codex/worktrees/repair-production-migration-history/umanews`
- branch：`codex/repair-production-migration-history`
- parent：`main@dc85e6a94b3bbae03ff6924b3d5a35e0bba7728a`
- 生产应用镜像：`sha256:b1fecc4624ac7fc181197156189b6326a40abb36f287feae72c9a2f533341a73`
- 生产 recorder：`0067`、`0070`；`0068/0069/0071` 未 applied。

## 2. 只读生产证据

- `0070` applied at `2026-08-02 05:07:24.615789+00`。
- receipt table 为 11 列，含 PK、approved SHA unique、operation-log one-to-one unique/FK、pattern
  index 与 owned sequence；7 条 receipt 的时间范围为 `05:07:40` 至 `06:15:53 UTC`。
- 7 条 receipt 的 operation log 均存在，JSON 字段类型全部符合合同。
- 受审 baseline：receipt rows SHA `99410674…49a4`、operation-log rows SHA `58f62742…68a1`、
  FK set SHA `90d2ba4d…de8c`；完整值保存在 `production_audit.json`。
- `stable_raceeventfieldchange` 没有 `0068` 的 11 个新增字段；不存在 `0069` 的 decision check、
  append-only trigger 或 function。
- 本轮探索只执行系统目录与业务计数/SHA 所需的只读 SQL，没有修改 recorder、schema 或业务行。

## 3. 阶段门禁

### R0：方案与审核

已完成五份 durable artifacts、生产只读 baseline 与多轮独立审查；当前已知 finding 均已进入
RED→GREEN 修订。受审 graph 固定为 `0067→0068→0069→0071` 与 `0067→0070→0071` 双分支汇合，
禁止 recorder adoption/fake。

### R1：测试与实现

已完成 graph、catalog、artifact、关闭态 handoff、durable intent、restricted marker、B→B rollback
固定控制面与 markerless retry 实现。最新完整三 suite 为 `251 tests / 250 passed / 1 Docker-gated
skipped`，真实 PostgreSQL catalog/migration 专项 `23/23`；固定旧镜像双态容器 gate 另按下述 R3
证据为 GREEN。

### R2：代码审核与发布授权

多轮 reviewer finding 已逐项修复并回归。任何 commit/push/PR/merge/生产发布仍必须由主任务按最终
fingerprint 和用户授权执行；本 worktree 尚未执行这些动作。

### R3：关闭态生产部署

重新备份数据库和 `.env`、tag 旧镜像、核对资源/locks/queues/flags。候选 v2 preflight 通过后才
生成 mode `0600` no-clobber before artifact。drain/stop 后，candidate one-shot 消费精确 artifact
path/SHA 做关闭态二次核验；一致后才执行 `0068/0069/0071`。失败按 design checkpoint 恢复。
固定旧生产 image
`sha256:b1fecc4624ac7fc181197156189b6326a40abb36f287feae72c9a2f533341a73` 已在本地精确导入，
并对隔离 PostgreSQL 16 的 `{0068,0070}` / `{0069,0070}` 两态完成真实关闭 flags 容器 smoke；
health、ping、read-only/write-denied、日志与 audited digest 均通过，技术门禁为 GREEN。

### R4：Release B 数据阶段

部署与 postflight 通过后才生成 v2 census；人工审核与门禁通过后执行回填，最后启动 2025
`full_network=true`。网络暂时失败按精确 checkpoint 最多 6 run；确定性错误停止并一次性报告。

## 4. 回滚与互斥

- 不复用上次发布锁、race-live intent、候选 image 或备份作为新发布证据。
- 不与外部 import、P0 写入、race-live、historical apply 或其他 migration 并发。
- `0068/0069` 已提交但 `0071` 未提交时保留 additive schema；只有固定旧镜像已在对应 partial
  schema/实际关闭 flags 上通过容器 smoke 才允许按受审 checkpoint 恢复核心服务。restricted-recovery
  intent 已在首次关闭态 verifier 后、任何 migration 前 durable 写入，不依赖失败后补写；partial/final
  active marker 只允许同 candidate/provenance 的 forward-resume。
- `{0071}` 的通用 B→B rollback 只执行目标 image 的 forward preflight；reverse 参数在 Compose 前
  明确拒绝。跨 schema reverse 属于另行审批流程。
- pre-v2 rollback 在 checkout 前保存 immutable v2 control image、脚本与 Compose override；markerless
  `not-required` 失败只允许 control-dir 专用 retry。control-state canonical SHA 绑定全部 copied helper/
  override 的 path/mode/bytes SHA，并在 lock 前/锁内以 nofollow fd 双验。
- completed control receipt 文件名绑定 target OID、初始 artifact SHA 与 state SHA；同 attempt completion
  no-clobber/idempotent，未来新 lock/artifact 可再次 rollback 同一 target，active state 单槽仍阻断并发。
- repair runtime parent 必须先于 child absence 判断校验；普通入口持锁后可用安全初始化器创建，
  stopped resume 不可创建。markerless retry 命令携带完整 attempt identity，completed-only 只可信定位
  exact receipt 并在任何 Git/Docker/Compose 前返回。
- historical initial-install 只接受 pre-0070 recorder 与无 runner trace 的首次纳管，使用 legacy single
  migration owner；无 flag 和 0070+ 始终走/受 v2 gate。旧 image smoke 的零写核心证明改为专用
  PostgreSQL 非超级只读 role 与权限撤销，旧 image 写 probe、管理员 digest、服务/日志共同 fail closed。
- schema preflight 必须 recorder/catalog-first；`receipt_audit_safe=false` 时禁止 live receipt collection，
  只消费 deterministic drift JSON。OperationalError 是运行故障，不能作为 drift 继续。
- rollback 目标 0071 必须以 `git show` 原始字节匹配受审 SHA/dependency allowlist；仅 legacy/repaired
  两个 operations 相同的版本允许 B→B，任何漂移在 checkout/build 前停止。
- receipt constraint/index 必须完整 set equality；额外 CHECK、UNIQUE、index 与 invalid/unready/non-live
  等语义漂移全部 fail closed，catalog 范围仍限显式用户表，不含 system/TOAST。
- rollback release 必须执行 pinned-control migrate-verify → exact-target collectstatic → pinned-control
  complete-intent。target override 只改 web.image 并复用基础 static volume；target ID 前后均绑定 artifact。
  static/ID/completion 失败保留 control-state、禁止启动，并由 markerless/forward-resume 精确重试。
- 任一 receipt/schema/plan digest 漂移立即停止。

## 5. 当前状态

当前已完成生产只读探索、方案、应用/运维实现、SQLite/隔离 PostgreSQL/发布编排测试、审查修订，
以及固定旧生产 image 的双 partial-schema smoke。准确实现与测试证据见
`design.md`、`tasks.md`、`test_cases.md`；当前已知唯一发布技术门禁已转为 GREEN。

旧镜像证据来自生产只读 `docker save` 后的本地精确导入；两次正式 gate 分别覆盖 `{0068,0070}`
和 `{0069,0070}`。fixture env-string、`post_migrate` 与首次 role auth 的三次 pre-smoke/setup 失败均
完成清理，不计作 gate；密码参数化修复后两次正式运行才构成 GREEN 证据。全部临时容器、network、
role 已清理，生产无容器操作或数据库写入。

仍未执行 commit/push/PR/merge、生产 migration/服务重启、v2 census、回填或 2025 full-network run；
这些动作继续由最终 smoke 证据、最终 fingerprint 与用户授权控制，不能把本地 GREEN 表述为已发布。

发布前 P2 已把 recovery provenance 收紧到唯一受审的 `forward-resume`。普通
deploy/manual/rollback/initial-install 会在 host 与容器两层忽略旧环境，只用当前 preflight artifact
创建/完成 intent；required resume 仍从原 artifact/control-state 恢复并验证精确 provenance。该修复
不改变生产状态，也不构成发布授权。修复后三套件 `256/256`（含 1 个 Docker 条件跳过）。

最终 commit review 的索引 owner P2 也已关闭：`0071` 两个 partial unique index 现在精确绑定当前
schema 与各自业务表，wrong-table PostgreSQL fixture 拒绝并恢复后复验通过。PostgreSQL 专项
`24/24`；该本地证据不改变生产状态或发布授权。
