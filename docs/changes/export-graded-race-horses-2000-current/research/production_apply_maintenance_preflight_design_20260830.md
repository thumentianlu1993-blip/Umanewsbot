# TRA 多年四地区 production apply 维护窗口预检设计

日期：2026-08-30（Asia/Shanghai）
状态：本地实现与测试已完成；尚未独立审查、发布或获 production apply 授权
副作用：0 TRA 请求、0 生产数据库写入、0 服务或配置变更

## 1. 结论

production apply 不能只消费一份先前生成的静态 proof。预检必须在同一个 host-local deployment lock
持有周期内完成，且从停止 Beat、生成只读证据、即时复核、执行 commit 到 verifier 结束都保持原 token
连续持锁。proof 只是短时、精确绑定的输入快照；它不打开 maintenance、不打开任何
`RACE_DATA_SYNC_*` 开关，也不单独授权 apply。

本 change 的维护窗口采用以下顺序：

1. 以 allowlist action 取得 `/tmp/umanews-deployment.lock`，后续只允许原 token verify/release；
2. 停止 Beat，保持 web 与普通 worker 的既有恢复契约；不得启动专用 `race_sync_v2_worker`；
3. 等待全部预期普通 worker 完整、二次一致地 idle；
4. 生成 candidate image 内的只读 preflight artifact；
5. 在同一锁内紧邻 commit 再次复核 DB、settings、Celery 与 Redis；
6. 只对 artifact/release/preflight 精确 SHA 全部匹配的下一个 plan/region ordinal commit；
7. 立即运行 verifier；失败时 safe-stop，不跳过 ordinal；
8. 外层部署协调器恢复关闭态服务拓扑并由原 token release。内层 apply wrapper 不 acquire/release 锁，
   也不自行 stop/start 服务。任何异常都不得清理或消费 `race_live`。

## 2. Proof 边界

### 2.1 Schema 与有效期

建议 schema：`p0-horse-production-maintenance-preflight.v1`。artifact 必须是新建的 `0600` 普通文件，
父目录必须为 `0700`、非 symlink，最大有效期 5 分钟。canonical JSON byte SHA 是唯一 proof identity。

artifact 至少绑定：

- `window_id`；
- deployment lock 的 action、started-at、compose file、token SHA-256 与 lock metadata SHA-256；
- candidate revision、image ID、image revision；
- reviewed artifact SHA、exact package manifest SHA、release candidate SHA、release manifest SHA；
- `apply_plan_id`、source rolling `batch_id`、region、ordinal 与 expected previous completed ordinal；
- production database identity SHA 与 migration leaf set；
- 生成时间、过期时间、检查结果与每类计数；
- `network_requests=0`、`database_writes=0`。

proof 不保存原始 deployment token、数据库口令或 Racing API 凭据。deployment lock token SHA 只用于证明
窗口连续性，不能据此 release 锁。

### 2.2 Exact 输入

生成、消费和 commit 前复核必须拒绝：

- artifact/package/release/candidate 任一 SHA 或 byte 内容漂移；
- package extra/missing member、symlink、非普通文件或路径逃逸；
- proof schema、window、region、ordinal、revision、image 或数据库 identity 不一致；
- proof 过期、未来时间、重复用于另一个 ordinal；
- deployment lock absent、action 不在 allowlist、metadata 漂移或 token SHA 不一致。

同一 ordinal 的已完成 receipt 重放可以零业务写返回原结果，但必须先验证 receipt 与当前 after-state；不得把
旧 proof 重用于新的 commit。

## 3. 现场只读检查

### 3.1 迁移与代码身份

- `MigrationExecutor` 计算 migration plan，必须为空；
- migration leaf set 必须与 candidate release 固定值完全相等；
- candidate Git revision、image ID 与 OCI revision 三者必须一致；
- database identity 必须与同一维护窗口内的 preflight 绑定一致。

### 3.2 十个赛事同步开关

以下十项必须逐项存在且严格为 `false`，不得只依赖一个聚合 dataclass：

1. `RACE_DATA_SYNC_ENABLED`
2. `RACE_DATA_SYNC_SCHEDULER_ENABLED`
3. `RACE_DATA_SYNC_ALLOW_NETWORK`
4. `RACE_DATA_SYNC_SCHEDULE_APPLY_ENABLED`
5. `RACE_DATA_SYNC_RACECARD_APPLY_ENABLED`
6. `RACE_DATA_SYNC_RESULT_APPLY_ENABLED`
7. `RACE_DATA_SYNC_RESULT_PUBLIC_ENABLED`
8. `RACE_DATA_SYNC_CORRECTION_APPLY_ENABLED`
9. `RACE_DATA_SYNC_LIFECYCLE_APPLY_ENABLED`
10. `RACE_DATA_SYNC_FUTURE_DISCOVERY_ENABLED`

同时要求 race-live scheduler/monitor/region 开关全部关闭。预检不得修改任何开关。

### 3.3 数据库活动

以下任一计数非零即失败关闭：

- `ExternalDataImportRun.status=started`；
- 任一 `ExternalDataImportLock.locked_by_run IS NOT NULL`；
- 其他 `HorseProfileCompletionRun.status=running`；
- 同 plan/region 以外的 active `HorseProfileProductionApplyBatch.status=claimed`；本次 claim 只能按 exact PK 排除；
- `RaceEventLiveTracking` 存在 active attempt 或 claim；
- `RaceEventLifecycleControl` 存在 claim；
- `RaceResultReviewRun.status=claimed`；即使 lease 已过期也仍视为 active，过期不等于 terminal；
- 写链相关 `TaskExecutionLog.status=started`。

生成 proof 时排除的“本次 completion run”必须由 exact run/batch identity 指定，不能按时间或用户名猜测。

### 3.4 Celery、Beat 与 Redis

- host evidence 必须证明 Beat stopped；
- `race_sync_v2_worker` 与 `race_live_worker` 必须 absent/stopped；
- 所有 expected ordinary worker 都必须出现在 ping、active、reserved、scheduled、第二次 active 的完整一致快照；
- active/reserved/scheduled/second-active 全部为 0；partial snapshot 或 inspector error 都失败关闭；
- Redis `celery=0`、`race_sync_v2=0`；
- `race_live` 只记录长度，不要求为 0，也绝不 purge、delete、pop、ack 或启动 consumer。

host process evidence 还要固定实际容器 ID、镜像 ID、running/health 状态与采集时间，不能只依据 Django
settings 推断主机拓扑。

## 4. 防竞态消费

commit 接口必须显式接收：

- preflight artifact path 与 expected SHA；
- reviewed artifact/package/release/candidate 的全部 expected SHA；
- window、batch、region、ordinal；
- expected revision/image/database identity；
- deployment lock metadata 与 expected token SHA。

调用方在进入 Django commit 前运行 `deployment_lock.sh verify`。Django 在事务开始后先重复所有可在
DB/settings/Celery/Redis 现场核对的检查，再取得 apply ledger/advisory/table locks；host wrapper 在 commit
返回后、verifier 前后再次 verify deployment lock。只要任一环节失败，事务回滚且保持下一 ordinal 未完成。

预检与 commit 都禁止网络请求。proof 生成成功只表示当时读到关闭态，不等于 maintenance 已开启，也不等于
用户或 reviewer 已批准该 release。

## 5. 测试矩阵

必须至少覆盖：

- pending migration 与错误 leaf set；
- 十个赛事同步开关逐项为 true；
- race-live scheduler/monitor/regions 任一开启；
- active import run、任意 import lock、其他 running completion；
- live tracking/lifecycle/result review claim，包括 expired-but-claimed；
- started write task log；
- Celery ping/active/reserved/scheduled 任一 partial、丢 worker、二次 active 漂移；
- `celery` 或 `race_sync_v2` 非零；
- `race_live>0` 仍可通过且长度前后守恒；
- stale/future proof、wrong artifact/package/release/candidate SHA；
- wrong revision/image/database identity、lost/drifted deployment lock；
- proof 用于错误 batch/region/ordinal；
- commit 中途异常整批 rollback；
- completed ordinal exact replay 零业务写，after-state 漂移时失败；
- verifier 失败后不推进后续 ordinal；
- inner wrapper 无论 success/failure 都不 acquire/release、不 stop/start；外层协调器始终只用原 token 恢复服务并
  release。

SQLite 只用于纯规则与事务单元测试；锁、并发、rollback 与 receipt/reverse 必须在隔离 PostgreSQL 16 复跑。

## 6. 与当前生产窗口的关系

当前 PR129 关闭态 rollout 仍由其他 release coordinator 持有边界；英国 TRA 样本、proof、canonical 和本
production apply 都保持暂停。本设计不授权 acquire、不接管别人的锁，也不修改共享 registry。只有收到赛事阶段
显式重开、现场内存与运行态通过，并且本预检与 apply ledger/reverse 实现完成后，才进入新的精确 G3。

## 7. 本地实现与验证（2026-08-30）

- `p0_horse_production_preflight.py` 生成/消费 0600、5 分钟、exact-SHA proof，逐项检查迁移、10 个同步开关、
  race-live 开关、外部 import/lock、completion/apply claims、历史赛事 claims、TaskExecutionLog、Celery 和 Redis；
- `capture_p0_horse_production_host_preflight.py` 固定 lock metadata/token SHA、candidate revision/image 和服务拓扑；
  `run_p0_horse_production_apply_locked.sh` 只消费外层现有原 token，不管理锁或服务生命周期；两层均拒绝可信
  runtime 根以下的中间目录 symlink，不能靠最终文件为 regular file 绕过 containment；
- `HorseProfileProductionApplyBatch/Receipt/ReverseReceipt` 实现 plan/region 连续 ordinal、唯一 active claim、失败后
  exact resume、completed replay 零写、同事务 before/after receipt 和 after-state drift guard；receipt 模型与后台
  均不可修改，反向恢复默认关闭，必须完整绑定批次身份/state SHA，并拒绝影响未捕获的后来关联行；
- production commit 使用 database-only policy，不自动发布页面或发送任何消息；direct legacy commit 在生产门禁
  开启时被拒绝，必须走 rolling batch；
- SQLite 相关回归 `288/288`、host/wrapper `10/10`、Django check、migration check、shell syntax、diff check 全绿；
  独立临时 PostgreSQL 16 的事务/锁/rollback/同 ordinal 并发 claim 为 `9/9`，容器随后自动删除。

这些是当前 worktree 证据，不绑定最终 commit/image，也不替代独立审查、custom-format 写前备份、现场 fresh
preflight、生产 verifier、用户精确 apply 授权或 PR129 owner 的赛事阶段重开。
