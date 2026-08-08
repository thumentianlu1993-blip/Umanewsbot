# 生产 migration history 一致性修复设计

## 1. 根因

receipt migration 原始拓扑是 `0067 -> receipt`。生产在 `2026-08-02 05:07:24 UTC` 记录
`0070_horse_identity_evidence_commit_receipt`，16 秒后写入第一条 receipt。Git 中把该文件从
`0068` 重命名为 `0070` 并把 dependency 改为 `0069` 的提交时间晚于生产 recorder，导致代码把
一个已经独立应用的 migration 重新解释成未应用父节点的子节点。

实际 schema 与该时间线一致：receipt 分支完整，race-data-sync 分支完全未应用。错误不是
`0068/0069` DDL 的隐性部分成功，也不是 receipt 表缺失。

## 2. 目标 graph

```text
                         +-> 0068 field audit -> 0069 ledger guards -+
0067 Release A ----------+                                         +-> 0071 Release B
                         +-> 0070 identity evidence receipt --------+
```

- `0070.dependencies = [("stable", "0067_historical_calendar_release_a")]`
- `0071.dependencies` 同时包含 `0069_race_data_sync_pipeline_a_ledger_guards` 与
  `0070_horse_identity_evidence_commit_receipt`

这是对真实历史的 graph 校正，不是 recorder adoption。生产现有 `0070` 记录在新 graph 中合法；
executor 只补齐另一分支再进入汇合节点。

## 3. 为什么不改 recorder

删除 `0070` 后重跑会触发既有 receipt 表的 `DuplicateTable`，除非再引入复杂的 state/database
分离 adoption；手工插入 `0068/0069` 又会把不存在的字段和 guard 伪装成已应用。恢复双分支 graph
既保留实际执行历史，也允许 Django 正常执行真正缺失的 DDL，因此风险最小。

## 4. 受审生产 baseline

`production_audit.json` 是候选 commit 内受 review/fingerprint 保护的 repair-state 发布输入，不能由
部署环境变量覆盖。它只约束 `{0070}`、`{0068,0070}`、`{0069,0070}` 三个修复状态；普通
`{0071}` B-to-B 发布/回滚不永久绑定首次修复时的 7 行数据，而是在 before artifact 中冻结当次 live
receipt/operation-log/FK digest，并在关闭态逐字节比较。当前 repair expected 值为：

候选 Docker image 只把这一份受审 JSON 复制到
`/app/docs/changes/repair-production-migration-history/production_audit.json`，与 schema service 的
`AUDIT_PATH` 精确一致；禁止为了提供 baseline 而复制整个 `docs/`。

- production DB identity SHA-256
  `a986cc11149981c54e9d4915ad35e7c46e9382584d6670c8f950eceda26e471c`；
- receipt count `7`；named-object rows SHA-256
  `d9866c0330de5a20ca5ca27acbbeda3c19b6575b215c454b0d367a37ed72c557`；
- referenced operation-log count `7`；rows SHA-256
  `e49ae6f6d28a04b059d139c59a998a6aeb793ee4bde47623cfe482e975c9814c`；
- scalar operation-log FK set SHA-256
  `7a0cb0d7117dcbe0663b20869b637a8434a8aea63f83c3940ced5cf9fdf990b1`。

canonicalization 固定为 UTF-8 JSON、`ensure_ascii=false`、key 排序、紧凑 separators；SQL 行按
主键升序，JSON object key 排序而 array 保持原顺序；datetime 统一 UTC、6 位微秒、`Z` 后缀；
SQL NULL 编码为 JSON `null`。canonicalization version 固定为
`named-object-scalar-fk/v1`；receipt/op/FK IDs 与三组时间边界也是比较字段，不是说明性元数据。

receipt 字段全集为 `id/created_at/updated_at/approved_sha256/artifact_sha256/approved_by/
approved_profile_ids/before_after/evidence_summary/result_payload/operation_log_id`。operation-log
字段全集为 `id/action_type/target_type/target_id/detail/created_at/admin_id`。FK set 按 receipt 主键
排序后只编码 `operation_log_id`。因此 receipt 非 FK 字段、operation-log 内容或 FK 映射任一变化
都会与 expected baseline 不同。

最初 SHA 由一次临时 raw SQL/Django shell 生成：cursor tuple 被编码成 positional JSON arrays，FK
被编码成 `[[id], ...]`。正式 runtime collector 使用 ORM `.values()` named objects 与 `[id, ...]`，
所以相同数据必然产生不同 SHA。两份发布前备份中的目标 receipt/op 行字节一致，二次只读 collector
也保持 count `7`、DB identity、IDs 与 2026-08-02 时间范围不变，根因因此锁定为生成口径而非数据更新。

唯一生成入口 `generate_migration_history_production_audit` 在 PostgreSQL
`REPEATABLE READ READ ONLY` 事务内直接调用 `collect_live_production_audit()`，只向 stdout 输出单行
canonical JSON，不改文件。loader 只接受 v2 完整字段集、精确 canonicalization version、升序唯一
ID/FK 列表与完整 time-bound 结构；missing/extra/错序均 fail closed。

## 5. Preflight 与关闭态 handoff 合同

候选镜像在停服务前执行只读检查，输出 contract version v2：

- applied stable nodes、canonical leaf set、unknown nodes、forward migration plan；
- receipt table 的列/type/nullability、PK、unique、FK、pattern index、sequence ownership 与 row digest；
- `0068` 11 个字段及 observation FK 的存在/精确性；
- `0069` decision check 的精确允许值表达式、append-only trigger/function 的存在/精确性；同名
  function 必须且只能存在一个无参数 target signature，任何 overload 都拒绝；
- `0071` 新旧唯一约束状态；
- candidate commit/image 与 production DB identity。
- 上述 live count/SHA 与候选内 `production_audit.json` 的 expected 值逐字节比较。

每个 migration 的 recorder 状态必须与对应 schema contract 一致：

- 未记录：对象必须完全不存在；
- 已记录：对象必须全部精确存在；
- 部分存在、额外同名对象或定义漂移：`ok=false`。

允许的发布前 leaf set 只包括：

1. `{0070}`：当前生产；计划必须为 `0068,0069,0071`。
2. `{0068,0070}`：仅 `0068` 已完整提交的恢复点；计划必须为 `0069,0071`。
3. `{0069,0070}`：race-data-sync 分支完整的恢复点；计划必须为 `0071`。
4. `{0071}`：部署后/B→B 状态；计划必须为空。

普通 deploy 不硬编码 `{0070}`，而由候选只读识别上述合法状态并选择 static-repair 或 live-handoff
audit policy，因此首次 repair 后的 `{0071}` 可继续正常 B-to-B 发布。
但两个 partial leaf 不是普通合法入口：`deploy`、`manual-release`、`rollback` 一律拒绝；只要 canonical
active marker 存在，即使 live 已是 `{0071}`，三个普通入口仍一律拒绝。只有 action
为 `forward-resume` 且 canonical marker 的 provenance/candidate/action 与 live partial state 全部匹配
才可生成 handoff。rollback 从 fresh artifact 提取并导出 DB identity，不能在 release orchestration
中丢失该绑定。

rollback 的目标资格必须在 checkout 前读取 `git show TARGET_OID:server/stable/migrations/0071...py`，
并同时匹配仓库受审 allowlist 中的 exact content SHA 和 literal dependencies。legacy 0071 只依赖 0070，
repaired 0071 汇合 0069/0070；两者 operations 完全相同且均兼容已经应用的最终 Release B schema，故
分别受审列项。未列出的 placeholder、dependency 或 operation 漂移都不是 B→B 目标。

wrapper 使用重复的 `--expected-migration-leaf-set` 表达完整集合，禁止继续把逗号列表误解为多个
单 leaf 候选。任何其他组合停止。

第一次 preflight 在宿主 `runtime/migration_history_repair/preflight/` 下以新目录保存 JSON：目录
mode `0700`、artifact mode `0600`、当前用户 owner、regular file、禁止 symlink，使用随机 nonce
和 no-clobber 原子发布。读写均先以 `O_DIRECTORY|O_NOFOLLOW` 打开可信 parent，再以该 dirfd
创建/读取 basename，避免 parent path swap；artifact 包含 expected/live baseline、catalog digest、applied nodes、leaf
set、plan、candidate commit/image、DB identity、Compose file、deployment-lock token SHA 与生成时间；
整个无签名 payload 另算 `artifact_sha256`。路径和 SHA 由 deploy wrapper 传入 release
orchestration，不能自动选择“最新文件”。

receipt catalog 使用 fresh PostgreSQL 生成的完整 constraint/index set 作为精确合同：四个 constraint
（PK、approved unique、operation-log unique、deferred PROTECT FK）与四个 index（对应三个 constraint
backing index 和自动 varchar pattern index）。比较名称、列序、method/opclass、predicate、unique、
valid/ready/live 与 FK action/deferrability；任何额外 CHECK、UNIQUE 或普通 index 也属于 drift。

web/worker/beat/race-live 全部停止后，`run_release_tasks.sh` 把该精确 artifact path/SHA 显式传入
release phases。rollback 的 pinned control image 以 `migrate-verify` phase 调用
`deploy/docker/run-release-tasks.sh`，并在调用 `migrate` 前先运行关闭态 verifier：重新
验证文件 trust、candidate/DB/Compose/deployment-lock binding，重新计算 recorder、schema、plan、
receipt 与 operation-log digests，并与 artifact 和受审 baseline 逐字节比较。任一变化直接退出，
`manage.py migrate` 调用次数为零。验证后没有长驻应用 writer；部署锁持续持有，发布 preflight
还必须证明 external import/P0/historical/race-live one-off 为零。关闭态 verifier 通过后、任何 migration
之前，在同一 deployment lock 和 one-shot 内以 `fsync(file)+fsync(parent)` no-clobber 持久化 active
recovery intent；intent 绑定 candidate commit/image、发起 action、原始 artifact SHA、DB identity 与
初始 `{0070}`。随后立即运行 `migrate`，两者之间禁止插入其他操作。这样进程在 `0068`、`0069` 或
`0071` commit 后突然退出时，恢复授权已经存在，不依赖失败路径事后补写 marker。

`manual_release.sh` 在新 deployment lock 下证明四个应用服务停止后现场生成 fresh handoff，不接收
调用方遗留 handoff。restricted resume 只用旧 artifact SHA 校验 marker provenance，随后在同一新锁
下为当前 partial leaf 生成 fresh handoff；关闭态 verifier 只消费新 artifact。migrate 成功到
`{0071}` 后，rollback 暂不完成 active marker。host wrapper 先核对 target tag 的 image ID 与 artifact
candidate ID 相等，再生成仅覆盖 `web.image` 的临时 Compose override，以 exact target image 执行唯一
`collectstatic --noinput`；基础 Compose 的 static volume 定义不被覆盖。成功后再次核对 target image ID，
再由 pinned control image 的 `complete-intent` phase 原子转换 marker。`migrate-verify` 输出恰好一条
受限协议行绑定 ensure 时的 marker dev/inode；host 只接受唯一合法值并把同一 identity 传入 completion，
不得在 static 间隔后重新 ensure/接受 replacement。normal deploy/initial-install 仍以
同一 image 的 `all` phase 串行 migrate、completion、collectstatic，不受 rollback split 影响。
若中断恰好发生在 migrate 已提交 `{0071}`、marker 尚未转换的边界，resume 允许同一可信 partial
marker 授权精确 final catalog/audit，幂等完成 marker transition 后继续；任意其他 final/marker/
candidate/action 组合均拒绝。

active marker 的完成转换必须把内容认证与文件对象身份绑定为同一可信 fd，且不得再执行
`stat(path) -> unlink(path)`。状态机在可信 parent dirfd 内先原子 rename
`restricted-recovery.json -> restricted-recovery.transition.json`，重新以 `O_NOFOLLOW` 验证 transition
slot 的完整 payload 与 dev/inode/owner/mode，再原子 rename 为绑定 marker SHA 的 completed receipt。
两个 rename 都必须使用内核 no-replace 语义：Linux 为 `renameat2(RENAME_NOREPLACE)`，macOS 为
`renameatx_np(RENAME_EXCL)`；平台或 libc 不提供对应原语时 fail closed，禁止退化为会覆盖目标的
普通 `rename`。destination 在检查后被并发创建时，源和既有 destination 都必须原样保留。
active 与 transition 同时存在、伪造 transition、任一 identity 漂移或 transition 期间重新出现 active
都 fail closed，且不删除 replacement。进程在第一次 rename 后退出时，以唯一可信 transition slot
幂等续跑；第二次 rename 后退出时，以精确 completed receipt 幂等确认。

handoff artifact 必须签名绑定 `recovery_intent_mode=required|not-required`。初始 repair 与
`forward-resume` 为 required：ensure 后 marker/transition 被删、替换或发生冲突时，completion 必须
失败并阻止服务重启；只有普通无 marker 的 `{0071}` B-to-B 才允许 not-required no-op。target
collectstatic 失败、target ID 前后漂移或 control completion 失败时，control-state 保持 active 且服务
保持停止；markerless 专用 retry 与 rollback forward-resume 都重跑幂等 verifier/migrate 后再次调用
target collectstatic，不允许在 control image 中补跑。
ensure 同时返回本次验证对象的 device/inode，one-shot completion 必须精确复用该 identity；即使
replacement 的内容、owner 和 mode 完全相同，也不能跨越 ensure→completion 边界。
final `{0071}` 上的 forward-resume 仍使用 reviewed-static production audit，不得切换 live-handoff
自设 baseline。通用 rollback 以目标 commit 包含准确 `0071` migration 和兼容 v1 release helpers 为
准，不要求后来加入的 `release_contract_v2` marker 文件。

`recovery_intent_mode` 只在精确 handoff artifact 本身实际包含该 SHA-bound 字段时启用。旧发布重试、
non-Release-B orchestration 或尚未生成该 artifact 的恢复入口，即使继承了陈旧同名环境变量，也必须
在当前子进程局部归一为 `not-required`，不得提前退出、污染 frozen race-live intent 或影响
`resume_stopped_release`。artifact 明确携带 required 时仍以 artifact 为权威；环境值缺失可从 artifact
恢复，环境值冲突则在任何服务停止前拒绝。

通用 B→B rollback 的控制面固定在 checkout 前：同一 deployment lock 下把当前受审 v2 控制镜像
另存 immutable tag，并把 preflight、application orchestration 与 host release wrapper 复制到 mode
`0700/0500` 的受限 runtime 目录。目标 checkout/build 后，`umanewsbot:prod` 保持目标镜像，同时另存
唯一 target tag；控制 one-shot 只通过 mode `0400` 的 Compose override 按 immutable control image ID
选择 `web`，禁止为了运行控制面把 control image retag 为 `umanewsbot:prod`。preflight 通过独立
binding image tag 读取目标 commit label/image ID，因此 artifact 绑定目标而不是控制镜像。
rollback 在 one-shot 前持久化 mode `0600` control-state，精确绑定 compose、control dir/image/
override 与 target commit/image/tag；失败后必须由下述 attempt-mode 专用入口重新验证这些绑定并继续
使用同一固定控制面，成功后才把 state 转为 completed。目标分支的 pre-v2 helper 不参与控制面执行。
`resume_stopped_release.sh` 在任何服务探测或启动前也必须执行 host marker/transition gate；active 或
transition 存在时提示改走 `forward-resume`，completed receipt 不阻断普通 stopped-service resume。

上述失败恢复还必须区分 attempt mode。若 handoff 为 `required`，restricted marker 是唯一授权，仍走
migration-history `forward-resume`。若 B→B rollback 在 `{0071}` 生成 `not-required` handoff 后 one-shot
失败，不得伪造 marker：rollback 在 checkout 前额外保存专用 `resume-rollback-release.sh`，control-state
同时绑定初始 artifact SHA、deployment-lock token SHA 与 `recovery_intent_mode`。操作者只能调用该
control 目录内的保存副本，并显式提供同一 target commit/image；不同 target、image、compose、HEAD、
control image/script/override 任一漂移都在服务动作前拒绝。重试失败保留 active state，成功才原子转为
completed。active control-state 与 marker/transition 一样阻断普通 deploy/rollback/stopped-service resume。

control-state 自身使用 `rollback-control-state/v1` canonical JSON；`state_sha256` 覆盖除自身外的全部
字段，其中 `control_files` 必须完整列出 preflight、application release、release-task wrapper、专用
resume、state creator 与 Compose override 的绝对路径、预期 mode 和 bytes SHA-256。创建器与 resume
都以 `O_DIRECTORY|O_NOFOLLOW` parent fd、`openat(O_NOFOLLOW)`、`fstat` owner/mode/dev/inode/size 读取，
禁止普通 path-following hash。resume 在获取 deployment lock 前验证一次、锁内再验证一次；两次都通过
后才允许 Git、Docker、Compose 或 preserved control script。相同 mode 的内容篡改、symlink/path
replacement、目录/文件身份漂移、缺项/多项或 state canonical SHA 漂移均零副作用拒绝。

completed control receipt 不能只按 target OID 命名，否则未来新 lock/new artifact 再次回滚同一 target
会与旧 receipt 冲突。文件名固定为
`restricted-recovery-control.completed.<target-oid>.<initiating-artifact-sha256>.<state-sha256>.json`。
completion 通过可信 parent dirfd 的 no-clobber hard-link 发布，再 fsync parent、删除 active slot 并再次
fsync；崩溃造成 active+completed 并存时，仅两者为同 inode、同 canonical state SHA 才可幂等收口。
completed-only 的同 attempt 重放只读验证后返回成功，不覆盖 inode/bytes；不同内容 destination 一律
拒绝。active state 仍是唯一单槽，因此不同 attempt 不可并发；前一 attempt 完成后，新 lock/artifact
产生不同 receipt identity，可再次合法回滚同一 target。

本变更的通用 rollback 只支持 B→B forward preflight。`SCHEMA_PREFLIGHT_DIRECTION=reverse` 不得被接受
后静默执行 forward；host wrapper 必须在 Compose 前明确拒绝并指向另行审核的跨 schema recovery。
底层 schema checker 仍保留 reverse invariants 供该独立流程使用。

## 6. 数据保护

repair-state 生产 preflight 保存 receipt contract digest、7 行按主键排序的业务字段 digest、operation-log 行与
FK 集合 digest，并要求三处等于受审 baseline；`{0071}` B-to-B 则以当次 before artifact 的 live 值为
baseline，在关闭态和 postflight 比较，不要求永远保持 7 行；
日志只报告计数和 SHA，不输出完整 payload。

`0068/0069` 是 additive field/guard DDL；`0071` 只切换历史赛历唯一约束。三个 migration 均不更新
既有业务行。迁移期间普通 web/worker/beat 停止，race-live 保持关闭，避免 schema/code 跨版本写入。

## 7. 精确 PostgreSQL catalog 合同

contract 不按对象名称或少量行为样例判断，而是从 `pg_catalog` 生成规范化语义定义：

- receipt：列序/type/typmod/null/default；PK/unique 的列序、predicate；FK target table/column、
  match/update/delete action、deferrable/deferred/validated；index unique/method/columns/predicate/
  operator class；sequence type/start/increment/min/max/cache/cycle、owned-by 与列 default。
- `0068`：11 列的相同字段合同；observation FK 的完整 target/action/deferrability/validation。
- `0069`：decision check 必须精确等于 PostgreSQL 实际生成的
  `decision = '' OR decision = ANY(ARRAY[四个业务值])`；校验仅消除括号、空白与无语义 type cast 后
  对完整 canonical expression 等值比较，禁止额外值、缺值、错列或不同逻辑；trigger
  timing/events/row-level/enabled/function identity；function
  catalog 保留所有 overload row，并要求目标名恰有一个无参数 signature，再核对 language、return
  type、volatility、security 与规范化 body。
- `0071`：新旧四个 constraint 的存在矩阵；新 partial unique 的 method/column order/predicate。
  predicate 只消除括号、空白与无语义 cast 后，分别与 PostgreSQL 实际合法表达式完整 canonical
  等值比较；`AND false`、`OR true`、换列或逻辑改变均拒绝，旧约束不得残留。

每类定义漂移都必须改变 catalog digest 并 fail closed，不能用小 fixture 的偶然行为等价替代。

## 8. 测试结构

- SQLite：graph consistency、production-like plan、fresh install、`0067/0070` 双分支汇合、正反状态。
- PostgreSQL legacy：从 `0067` 构造真实旧 receipt 分支与非零 receipt，记录 `0070`，再运行候选
  graph；验证数据 digest、全部 DDL 与 leaf。
- PostgreSQL fresh：从零到 `0071`，证明 receipt 只创建一次。
- PostgreSQL mismatch：缺表、缺 index/FK、额外/缺失 `0068` 列、错误 guard、recorder/schema
  不一致分别 fail closed。
- PostgreSQL catalog mutation：错误 FK target/action/deferrability、index 列序/operator class/
  predicate/method、sequence owner/default、observation FK、check predicate、trigger timing/events/
  body、`0071` partial unique predicate/columns 与旧约束残留逐类至少一个负例。
- Baseline/TOCTOU：分别篡改 receipt 非 FK 字段、operation-log 内容、FK 映射，以及第一次 preflight
  后再插入/修改行，证明关闭态 verifier 在 migration 前拒绝。
- Partial recovery：分别冻结在 `0068`、`0069`，验证只有精确 schema 才允许继续。
- Pinned old image：在临时 PostgreSQL 的 `0068-only` 与 `0069-complete` schema 上，以生产旧镜像
  digest 和关闭 flags 启动 web/worker/beat，验证 Django check、health、Celery ping、只读 ledger
  查询与零 UPDATE/DELETE；同时验证实际 `.env` flags、普通/race-live queue 与 one-off 均关闭。
- Deploy contract：candidate preflight 仍在 build 后、stop/release 前，且完整绑定 commit/image/DB。

## 9. 发布与回滚

发布前重新制作数据库备份与旧镜像 tag，不复用上次备份作为新恢复点。候选 preflight 通过后按
既有 drain/release orchestration 执行 `0068/0069/0071`。

- migration 前失败：旧服务不变。
- 普通 rollback 在取得 deployment lock 后、任何 `git fetch/checkout`、build 或 image 变化前检查
  canonical marker。marker 存在或 owner/mode/no-symlink trust 不成立时均 fail closed，且不得读取、
  改写、chmod、rename 或删除 marker，以免破坏原 candidate provenance。
- `0068` 或 `0069` 后失败：只有固定旧镜像 digest 与实际关闭配置已通过对应 partial-state 测试时，
  才能恢复核心服务；additive schema/guard 保留。该环境标记为 restricted recovery，只允许同一
  reviewed repair commit/image 的 forward resume，禁止普通 deploy、其他 migrate、race-live、
  race-data-sync 或数据任务。未取得该兼容证据时保持应用停止并人工选择 forward resume。
- `0071` 后应用异常：沿用 Release B 规则；除非 reverse preflight 通过且另获授权，不反向约束。
- 数据库或 receipt digest 漂移：停止并保全现场，由人工选择审核过的 forward repair 或备份恢复。

## 10. 非目标与残余风险

修改已发布 migration dependency 只在这里成立，因为它恢复的是该 migration 实际应用时的父节点；
不得推广为一般做法。残余风险是数据库在历史应用时可能存在未留存的临时工作树内容，因此以当前
精确 schema 与非零 receipt digest 为最终事实，不以 Git 时间线单独作为发布证明。

## 11. Runtime parent 与 completed-only retry

`runtime/migration_history_repair` 本身必须先于 child marker absence 做 owner/mode/no-symlink 验证。普通
deploy/rollback/manual release 仅在持有 deployment lock 后，通过 nofollow dirfd 创建缺失目录为
`0700`，并以 lstat/fstat 的 inode、owner、mode 交叉复验；stopped-service resume 不得创建或修复。

markerless rollback retry 的公开命令必须携带 target commit/image、initiating artifact SHA 与 canonical
state SHA。入口据此构造唯一 completed filename，在可信 parent fd 中枚举并读取 exact receipt；active
缺失时完成全部 state/control-file binding 验证后立即成功，active 存在时仍执行 lock 前与锁内双验。
任何同 target 的其他历史 receipt 都不得参与选择。

## 12. Pre-0070 initial-install 与旧 image 同步零写

historical runner 首次纳管是唯一非 Release-B handoff 分支。它必须同时满足显式 flag、既有健康基础
服务、无 runner 容器/network/secret/table/role trace，以及 recorder 不含 `0070/0071`；满足后仍只由
既有 one-shot 串行执行 migrate/collectstatic。默认/0070+ 分支不得由环境变量切换到此路径。

partial-state old-image smoke 为应用创建独立 `NOINHERIT` 非超级 role，撤销所有应用 schema table DML、
schema CREATE、database TEMP 与非系统 function execute，只授予读取所需权限并设置 default transaction
read-only。旧 image 在任何 daemon 启动前验证连接 identity/read-only，并在 nested atomic savepoint
向 recorder 执行必拒绝 INSERT。管理员通过 read-only transaction 对 recorder/关键表全行 canonical
JSON 聚合 digest 前后复核；daemon 的退出、write-rejection 或 error 日志均使 smoke 失败。

## 13. Recorder/catalog-first preflight

schema check 的第一阶段只读取 migration recorder 与 pg_catalog，并以纯 validator 检查 table presence、
columns/types/defaults、constraints、indexes、sequences、triggers/functions。第一阶段不安全时立即形成排序
去重 `drift_paths`，设置 `receipt_audit_safe=false`，不调用任何业务 conflict ORM 或 live production
audit。第一阶段安全后才允许读取 receipt/operation rows 并冻结 digest。

已知 catalog drift 是业务可判定的 `ok=false`，management command 输出 JSON 后 `CommandError`；不使用
宽泛 `DatabaseError` 捕获，因此连接断开、timeout 等 `OperationalError` 仍明确暴露。破坏性 PostgreSQL
fixture 必须置于 savepoint，并在 tearDown 显式 rollback，避免污染共享测试 schema。

## 14. Provenance artifact 的 action 隔离

`RESTRICTED_RECOVERY_PROVENANCE_ARTIFACT_SHA256` 只描述既有 marker 的原始 handoff。普通
`deploy/manual-release/rollback/initial-install` 不得使用继承值；host 入口显式 unset，容器 release
task 根据已生成 artifact 的 `handoff_action` 再次分流，ensure 不携带 provenance，completion 使用
当前 `RELEASE_B_PREFLIGHT_ARTIFACT_SHA256`。

只有 `forward-resume` 允许把受审入口从原 artifact/control-state 恢复的 SHA 传入。该 SHA 先做严格
格式检查，再由 handoff 与 marker verifier 对 candidate/image/DB/action/provenance 进行真实绑定验证。
因此普通 action 的残留环境不会在 migrate 后误入 restricted completion，伪造 action 也不能绕过
artifact/marker 验证。

## 15. Release B partial unique index owning relation

两个 `0071` index 的合同不仅包含名称、btree/unique、列、opclass、predicate 与
valid/ready/live，还绑定 PostgreSQL 当前 schema 和精确 table：
`uq_race_event_series_edition` 只能属于 `stable_raceevent`，
`uq_hist_target_active_series_year` 只能属于 `stable_historicalraceeventtarget`。

catalog index 查询除目标表 allowlist 外，还按两个受审 index name 补充收集当前 schema 内对象。这样
原 index 被删除、同名对象被建到其他 fixture/业务表时，validator 能看到错误 owner 并输出对应
`0071.*` drift，而不是依赖名称缺失的间接结果。其他 schema 的对象不能满足当前 schema 合同。
