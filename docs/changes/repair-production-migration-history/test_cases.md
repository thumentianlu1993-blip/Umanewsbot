# 生产 migration history 一致性修复测试用例

## 1. RED

1. production-like recorder 仅 applied `0067/0070` 时，当前 graph 的
   `check_consistent_history()` 抛出 `InconsistentMigrationHistory`。
2. 当前 wrapper 无法表达 `{0068,0070}`、`{0069,0070}` 这类完整 leaf set。
3. 当前 preflight 即使 receipt table 缺 index/FK 或 recorder/schema 不一致也不会阻断。
4. 当前第一次 preflight 后修改 receipt/operation log，release task 不会在 migration 前重新比较
   受审 baseline 与不可变 handoff artifact。

RED 必须来自上述目标能力缺失；不得用语法错误、错误 fixture 或不可达 PostgreSQL 代替。

### 1.1 自动化 RED 落点

- `server/stable/test_migration_history_repair.py`：production-like graph、四种合法 leaf-set/plan、
  非法 partial state、受审 baseline 三类 SHA 漂移、catalog 语义漂移、artifact trust、关闭态 verifier
  零 migrate、restricted recovery binding。
- 图与 plan 用例直接加载当前 Django migration graph；其失败必须是 `0070` 仍依赖 `0069` 或
  `0071` 尚未汇合双分支，不允许用伪造 migration module 代替。
- baseline/catalog/artifact/recovery 用例定义公开纯函数合同；实现缺失导致的 import failure 是目标
  能力尚不存在的 RED，后续实现必须让各负例进入业务断言，而不是跳过用例。
- PostgreSQL 真实 DDL、旧镜像容器 smoke 仍由后续专用 fixture 执行；本文件中的纯函数和脚本合同
  不能替代真实 PostgreSQL/catalog/container 证据。

### 1.2 2026-08-08 实际 RED 证据

production audit 口径修复另新增 `stable.test_production_audit_baseline`：首次运行 `5` 项中 `4` 项
因唯一生成命令和 raw-row builder 不存在而有效 RED；修正测试自身临时文件 patch 后，RED 仍稳定为
4 项目标能力缺失。固定 fixture 明确证明 positional receipt/op rows 与 nested FK 相对 runtime
named-object/scalar-FK 会产生三项独立 drift；ID missing/extra/wrong-order 也必须拒绝。

GREEN 后运行 migration repair、Release B、single-owner 与新 baseline 四套 SQLite suite：
`263/263` 通过，1 项既有 Docker 条件跳过；隔离 PostgreSQL 16 完整专项 `25/25`。新增 PG 用例捕获
唯一生成命令 SQL，确认存在 `SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY`，命令窗口
不含 `INSERT/UPDATE/DELETE`，输出 audit 字段逐项等于同一时刻直接调用 runtime collector 的结果。

以下命令均使用现有 SQLite 测试环境，Django system check 通过；非零退出来自目标能力缺失，
不是数据库不可达、语法错误或 fixture 漏建：

```text
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/Code/umanews/.venv/bin/python \
  server/manage.py test \
  stable.test_migration_history_repair.MigrationHistoryRepairGraphRedTests --noinput
```

- 结果：`2` 项中 `1` 项有效 RED、`1` 项通过。
- 失败点：production-like recorder 已包含 `0067` 全部祖先与 `0070`，仍由 Django 精确报
  `0070 ... applied before its dependency ... 0069`；证明不是测试漏放 `auth/contenttypes` 等祖先。

```text
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/Code/umanews/.venv/bin/python \
  server/manage.py test \
  stable.test_migration_history_repair.MigrationHistoryRepairLeafSetRedTests --noinput
```

- 结果：`2` 项有效 RED。
- 失败点：管理命令尚无可重复的 `expected_migration_leaf_set` 参数，当前逗号字符串只能表达“多个
  单 leaf 候选”，无法表达 `{0068,0070}` 这一完整集合；非法 partial-state 因此也没有对应门禁。

```text
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/Code/umanews/.venv/bin/python \
  server/manage.py test \
  stable.test_migration_history_repair.MigrationHistoryRepairBaselineRedTests \
  stable.test_migration_history_repair.MigrationHistoryRepairCatalogRedTests --noinput
```

- 结果：`3` 项有效 RED。
- 失败点：当前 schema service 不存在受审 baseline 比较器和 catalog 语义合同比较器；因此 receipt
  rows、operation-log rows、FK set 以及 FK action/index method/sequence owner/trigger events/
  partial unique predicate 的漂移尚不能 fail closed。

```text
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/Code/umanews/.venv/bin/python \
  server/manage.py test \
  stable.test_migration_history_repair.MigrationHistoryRepairArtifactRedTests \
  stable.test_migration_history_repair.MigrationHistoryRepairRestrictedRecoveryRedTests --noinput
```

- 结果：`6` 项有效 RED。
- 失败点：handoff/artifact service 尚不存在；release task 没有关闭态 verifier，模拟 verifier 漂移
  时脚本仍返回 `0` 并调用 migrate；host wrapper 也未传精确 artifact path/SHA、候选 binding 与
  restricted-recovery marker。
- 上述命令未连接生产、未运行 Docker/PostgreSQL、未执行 migration 或业务写入。

## 2. Graph GREEN

1. 修复后 `{0067,0070}` 通过 consistent-history，forward plan 精确为 `0068,0069,0071`。
2. `{0067,0068,0070}` 的 leaf set 为 `{0068,0070}`，plan 为 `0069,0071`。
3. `{0067,0068,0069,0070}` 的 leaf set 为 `{0069,0070}`，plan 为 `0071`。
4. 应用 `0071` 后唯一 leaf 为 `0071`，plan 为空。
5. fresh install 从零到 `0071` 成功，receipt table 只创建一次。
6. `0071` reverse 只回到双 leaf `{0069,0070}`；不反向删除 receipt 或 race-data-sync 分支。

## 3. PostgreSQL legacy fixture

1. 从 `0067` 创建与生产精确相同的 receipt branch，写入至少一条 receipt 和 operation log，再记录
   `0070`；迁移到 `0071` 后 receipt 行数、行 digest、PK/FK/unique/index/sequence digest 不变。
2. `0068` 11 个字段的 type、length、nullability 与 observation FK 精确。
3. `0069` decision constraint 拒绝未知值；UPDATE/DELETE trigger 拒绝修改 ledger，INSERT 正常。
4. `0071` 新唯一约束生效，旧约束不存在。
5. 连续运行两次 migrate，第二次 plan 为空且不产生重复对象。

## 4. Preflight fail-closed

1. recorder 有 `0070` 但 receipt table 缺失、列漂移、缺 unique/FK/pattern index/sequence 任一项时
   `ok=false`。
2. recorder 无 `0068` 但出现任一 `0068` 列，或 recorder 有 `0068` 但字段/FK不完整时停止。
3. recorder 无 `0069` 但出现同名 constraint/trigger/function，或已记录但定义不精确时停止。
4. 非法 leaf set、未知 stable node、计划顺序异常、DB identity/commit/image 不匹配时停止。
5. 合法四种 leaf set 分别只接受其精确 plan；不得用“node 已知”代替 plan 校验。
6. preflight 全程 read-only；query capture/PostgreSQL transaction 证明业务表与 recorder 零写入。
7. receipt 非 FK 字段、operation-log `detail/action_type/target/admin/created_at` 与 FK 映射分别篡改，
   均相对 `production_audit.json` 在 migration 前 fail closed。
8. 第一次 preflight 后插入/修改 receipt 或 operation log，关闭态 verifier 必须拒绝，mock/trace
   证明 `migrate` 调用为零；artifact 路径/SHA/owner/mode/symlink/commit/image/DB/lock 任一漂移同样拒绝。
9. receipt FK 的 target/delete action/deferrability/validated，unique/index 的列序/predicate/opclass/
   method，sequence owner/default 分别至少一个 catalog drift 负例。
10. `0068` observation FK、`0069` check predicate/trigger timing-events/function body、`0071` partial
    unique columns/predicate 与旧 constraint 残留分别至少一个 catalog drift 负例。
11. receipt 的 fresh PostgreSQL constraint/index 完整集合通过；分别 `ADD CHECK`、`ADD UNIQUE`、
    `CREATE INDEX` 后返回 `0070.constraint_set`/`0070.index_set`，fixture 以 savepoint rollback 恢复。
12. standard/lowcost rollback 对 reviewed legacy/repaired 0071 均通过；placeholder、改 dependency、改
    operation 均在 `git checkout` 与 Compose build 前失败，且错误目标字节不进入 release orchestration。

## 5. Partial-state 旧镜像兼容

1. 固定生产旧镜像 `sha256:b1fecc…41a73` 与实际关闭 flags，在临时 PostgreSQL `0068-only` schema
   启动 web/worker/beat；Django check、healthz、Celery ping、read-only ledger query 通过且无业务写。
2. 同一镜像在 `0069-complete` schema 重复上述测试；append-only guard 生效，静态/runtime SQL
   capture 证明旧 revision 没有 RaceEventFieldChange UPDATE/DELETE 路径。
3. 两态都断言 historical/race-data-sync/race-live flags false、相关 queues/active/reserved/one-off 为零。
4. partial-state 下普通 deploy/migrate 被 restricted-recovery marker 阻断；只有绑定同一 repair
   commit/image/artifact 的 forward resume 可进入关闭态 verifier。

### 5.1 2026-08-08 真实固定旧镜像证据

- 从生产主机以只读 `docker save` 导出旧镜像，在本地精确导入并核对为
  `sha256:b1fecc4624ac7fc181197156189b6326a40abb36f287feae72c9a2f533341a73`，平台为
  `linux/amd64`。生产未启动/停止/替换容器，未连接或写入生产数据库。
- 隔离 PostgreSQL 16 fixture 的 recorder 分别为 `{0068,0070}`（脚本状态名 `0068-only`）和
  `{0069,0070}`（`0069-complete`）；两次脚本均输出
  `old-image partial-state compatibility smoke passed`。
- 两次均依次通过临时 role TCP password authentication、`current_user` 与
  `transaction_read_only=on`、显式 recorder INSERT write-denied、旧镜像 Django check、web health、
  worker ping、beat running、三容器日志 clean，以及管理员 before/after audited digest 完全一致。
- 每次完成后临时 web/worker/beat、PostgreSQL、Redis、network 与只读 role 均已清理，不存在遗留
  fixture。旧镜像 partial-schema compatibility 的唯一技术门禁因此为 GREEN。
- 正式 gate 之前的 fixture env-string 解析失败与 Django `post_migrate` 失败都属于 pre-smoke setup
  failure，完成清理且没有形成 gate 结果；首次旧 role password authentication failure 同样发生在
  服务启动前，促成密码参数化与独立 TCP auth preflight 修复，不冒充兼容性失败或成功。

## 6. 回归与静态门禁

- Release B schema/部署测试、race-data-sync Slice A migration 测试、P0 receipt 测试保持 GREEN。
- `DB_ENGINE=sqlite python manage.py check`。
- `python manage.py makemigrations --check --dry-run`。
- migration graph/owner 检查与两份 Compose config 通过。
- shell syntax、compile、workflow contract 与 `git diff --check` 通过。
- 完整 stable 与冻结主线失败集合比较，不把既有范围外失败表述为全绿。

## 7. 发布验收

1. 新备份、旧 image、candidate commit/image、DB identity、flags、locks、queues 全部有证据。
2. preflight 保存 no-clobber before artifact；关闭态 verifier 消费同一路径/SHA并再次核对受审
   baseline 后，migration 实际只应用 `0068/0069/0071`。
3. postflight digests 不变，migration plan 为空，leaf=`0071`，服务恢复到同一候选镜像。
4. Release B 部署阶段不运行 v2 census、回填或 full-network；它们仍按后续门禁串行执行。

## 8. 2026-08-08 operations handoff 本地 GREEN 证据

```text
/Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_migration_history_repair --verbosity=1
```

- repair 专项 `45` 项中 `44` 通过、`1` 项默认跳过；跳过项是显式开启的真实 Docker build/image
  contract。其余覆盖真实 historical backfill flags、repair/B-to-B audit policy、DB identity 静态 baseline、
  dirfd artifact trust、migration 前 durable intent、canonical restricted marker、active marker 普通入口
  阻断、精确 decision/function-overload catalog 合同、无 `eval` shell 与 lock SHA 路径。

```text
/Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_migration_history_repair stable.test_historical_calendar_release_b --verbosity=1
```

- repair + Release B 组合 `78` 项中 `77` 通过、同一 Docker 项默认跳过。
- 隔离 PostgreSQL 16 专项 `9/9` 通过。真实 `pg_get_constraintdef` 为
  `decision = '' OR decision = ANY(ARRAY['applied','replayed','needs_review','rejected'])` 的带 cast/括号
  形态；合法定义通过，额外值、缺值、错列和逻辑替换负例继续 fail closed。

```text
/Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_single_migration_owner.ReleaseTasksContainerScriptTests \
  stable.test_single_migration_owner.HostReleaseWrapperTests \
  stable.test_single_migration_owner.DeployOrchestrationTests \
  stable.test_single_migration_owner.RollbackOrchestrationTests \
  stable.test_single_migration_owner.ApplicationReleaseOrchestrationTests --verbosity=1
```

- 当前列出的五个 single-owner/deploy orchestration class 为 `34/34` 通过；另含 rollback 固定控制面
  失败重试的定向组合为 `35/35`。active marker 负例证明
  rollback 在 lock 后、fetch/checkout/build 前退出，marker inode/mode/content 不变。
- normal deploy 的 fail-after-migrate harness 继续证明同镜像 all phase 中 marker transition 先于
  collectstatic；rollback split 则相反：control migrate phase 不调用 completion/collectstatic，target
  collectstatic 成功后才运行 control completion。
- migrate 返回 `47` 的 abrupt-death harness 证明 durable intent 已在 migrate 调用前完成，失败路径
  不再调用任何 post-failure marker recorder。
- pre-v2 one-shot 返回 `73` 时，`umanewsbot:prod` 从未被 control image 覆盖；active control-state
  保留精确 target/control 绑定，移除故障后同一 `forward-resume` 使用固定脚本、image ID 与 Compose
  override 完成并把 state 转为 completed。
- active→transition 与 transition→completed 两个 no-replace 边界都注入“预检查后并发创建 destination”；
  两次均以 `FileExistsError` 停止，源 slot 与竞争 destination 字节保持不变。
- markerless rollback 的专用恢复矩阵覆盖首次 one-shot `73`、同 target 重试再次 `73`、错误 target、
  普通 stopped-service resume 与最终成功：两次失败均保留 active state，错误 target/普通 resume 零服务
  启动，成功使用 pinned v2 control plane 并转 completed。RollbackContract + ResumeStopped 为 `19/19`。
- `SCHEMA_PREFLIGHT_DIRECTION=reverse` 在 Compose run 前明确失败；底层真实 reverse schema 负例仍为
  `8/8`，两种 rollback 与普通 forward 的五组发布编排为 `34/34`。
- artifact-only verifier 直接重算原始 handoff canonical SHA，并绑定原 deployment-lock token SHA、
  candidate、DB identity、Compose 与 artifact path；测试证明该模式不运行当前 live preflight。
- 标准与 lowcost markerless failure 都逐一篡改 `application-release.sh`、`preflight.sh`、
  `release-tasks.sh`、`resume-rollback-release.sh`、`create-control-state.py`、`compose-control.yml`：先临时
  加 owner write、修改 bytes、再恢复原 mode，六项全部在 lock/Git/Docker/Compose 前拒绝。另覆盖
  control-state 字段改变但不更新 `state_sha256`，以及 preflight path 换为 symlink；恢复原字节/路径后
  两种 rollback 均正常续跑。RollbackContract + ResumeStopped 更新为 `20/20`。
- 标准与 lowcost 分别连续成功 rollback 同一 target 两次；每种都生成两个文件名不同的 mode `0600`
  receipt，文件名精确包含 target OID、初始 artifact SHA、state SHA，payload canonical SHA 与文件名一致。
  对每个 completed-only attempt 重放 completion 均返回 `already-completed`，inode/bytes 不变。
  另模拟 hard-link 已发布但 active 尚未删除的崩溃边界，专用 retry 只收口同 inode state，零
  Git/Docker/Compose/release replay。RollbackContract + ResumeStopped 更新为 `22/22`；五组发布编排
  复跑 `34/34`。
- repair root 无任何 child 时仍先校验 parent；stopped resume 对 parent missing、symlink、mode `0755`、
  mock wrong-owner 四种状态均在任何 Compose `up` 前拒绝，可信空 `0700` parent 正常恢复。普通首次
  standard/lowcost deploy 则通过显式初始化器创建并复验 `0700` real directory。
- 模拟 completion 已 durable 删除 active、但 caller 尚未观察成功的 completed-only 崩溃边界：同 target
  同时保留另一历史 receipt，专用 retry 仍只按 target/artifact/state SHA 定位 exact receipt，可信复验
  后零 Git/Docker/Compose 返回；证明既可达又不 fuzzy-match。
- 第十二轮完成后完整三 suite 为 `211 tests / 210 passed / 1 Docker contract skipped`；shell syntax、
  新 runtime initializer Python compile 与 `git diff --check` 均通过。
- standard/lowcost 对 pre-0070 initial-install 均覆盖三态：显式 flag 只产生一个 legacy
  release-task run 并可达 migrate；相同 state 无 flag 在 v2 preflight 前置失败、零停服；0070+ 带 flag
  在 build/stop/run 前拒绝。container script 另验证 initial mode 精确为 wait→migrate→collectstatic。
- old-image smoke 静态合同要求无 `pg_stat_user_tables`，包含专用非超级 role、default read-only、撤销
  table/schema/database/function 写能力、旧 image current-user/read-only 断言、显式 recorder INSERT 拒绝、
  管理员全行 digest 与三个容器日志/运行态门禁；后续真实 Docker 双 partial-state 已按 5.1 正式通过。
- 第十三轮完成后完整三 suite 为 `215 tests / 214 passed / 1 Docker contract skipped`；相关 shell
  syntax 与 `git diff --check` 通过。
- 第十六轮 sabotage 覆盖：control `migrate-verify`/`complete-intent` 即使 collectstatic 被设为 exit 97
  也零调用；target override 精确只含目标 tag，沿用基础 static volume；target static 失败或前后 image
  ID 漂移时零 completion/零服务启动且 control-state 保留。standard/lowcost markerless retry 与 required
  forward-resume 均在失败后再次执行一次 target collectstatic 并成功完成；normal deploy 仍单次 all flow。
- 第十六轮完整三 suite 为 `230 tests / 229 passed / 1 Docker contract skipped`；PostgreSQL 专项仍为
  `16/16`。
- schema/call-order 纯函数负例证明 catalog drift 时 event/target ORM 与 live audit 均零调用；handoff
  初检 `ok=false` 不进行第二次 check 或 audit；`OperationalError` 原样上抛；management command 输出
  可解析 JSON 后 `CommandError`。
- PostgreSQL 真库在 `0070` recorded 状态分别 `DROP TABLE ...receipt CASCADE` 与 `DROP COLUMN
  artifact_sha256 CASCADE`：均返回 `production_audit_live=null` 及 exact `0070.table_presence`/
  `0070.columns`，另以 `ALTER COLUMN artifact_sha256 TYPE text` 锁定 `0070.column_semantics`；CLI 无
  ProgrammingError；每例由 savepoint tearDown 显式 rollback。PG 专项 `12/12`。
- 第十四轮完整三 suite 为 `219 tests / 218 passed / 1 Docker contract skipped`；Python compile 与
  `git diff --check` 通过。
- action gate 负测证明两个 partial leaf 对 deploy/manual/rollback 全部拒绝，forward-resume 缺少可信
  marker 也拒绝；同一 marker 只接受自己的 candidate/action/provenance 和 exact partial 或 `{0071}`
  边界。rollback 合同验证 fresh artifact DB identity 被导出到 release orchestration。
- marker transition 覆盖认证读取后、第一次 rename 前替换 active，第一次 rename 后崩溃续跑、
  active+transition 冲突、伪造 transition、第二次 rename 前后重新出现 active 与 completed-only 重放；
  replacement 保留且流程 fail closed，全路径断言不调用 `os.unlink`。
- final 0071 forward-resume 仍调用 reviewed-static audit；普通 B-to-B 才冻结 live baseline。required
  attempt 删除 marker 或替换为同内容新 inode 后 completion 失败，not-required 仅在 final 且无
  active/transition 时 no-op。
- rollback 目标缺少后置 `release_contract_v2` 但包含准确 0071/v1 helpers 时通过，缺 0071 仍拒绝；
  PostgreSQL 将任一 0071 unique index `indislive=false` 时精确 catalog verifier 拒绝。
- shell syntax、Python compile 与 `git diff --check` 通过。
- 完整三 suite
  `stable.test_migration_history_repair + stable.test_historical_calendar_release_b + stable.test_single_migration_owner`
  为 `202 tests / 201 passed / 1 Docker contract skipped`。新增兼容矩阵证明 artifact 不存在/无新字段时
  陈旧 `required` env 不泄漏；artifact 明确 required 时可自动恢复 mode，冲突 env 在服务停止前拒绝。
  原先 RaceLiveRetrySemantics `2`、RaceLiveStatePersistence `2`、ResumeStoppedRelease `1` 回归均转绿。
- 标准/lowcost rollback 的真实脚本 harness 在 checkout 时把目标三个 helper 替换为 pre-v2 桩：目标
  preflight 不产 artifact，target application/release helper 调用即返回 `97/98`。两条 rollback 仍从
  checkout 前保存的 v2 控制面生成唯一非空 artifact、运行 release，并记录 control/target image tags；
  证明不会对空 artifact 执行 sed，也不会调用目标 pre-v2 helper。
- `RUN_MIGRATION_REPAIR_DOCKER_CONTRACT=true` 的真实 image contract `1/1` 通过：容器内代码从精确
  `/app/docs/.../production_audit.json` 读取 DB identity，且 `/app/docs` 只有该最小文件。
- `deploy/smoke_migration_history_repair_old_image.sh` 已以精确生产旧镜像在两个隔离 PostgreSQL 16
  partial schema 上正式执行并通过；固定旧镜像 compatibility 技术门禁为 GREEN。该结论不等于已
  commit、发布或执行生产 migration。

## 发布前 P2：残留 provenance action 隔离

- RED：普通 `handoff_action=deploy` 注入旧的 64 位 provenance SHA 时，host wrapper 原样传入容器，
  ensure 与 completion 都错误使用旧 SHA。
- GREEN：普通 deploy 的 host 参数被清空；容器 ensure 使用空 provenance、completion 使用当前
  preflight artifact SHA，且顺序固定为 ensure → migrate → completion。
- forward-resume 正例继续精确传递原 provenance；ordinary 六入口的静态合同、initial-install、
  standard/lowcost rollback、markerless retry 与 required resume 均纳入回归。
- 最终三套件为 `256/256`（`255 passed / 1 Docker contract skipped`）。

## 发布前 P2：0071 索引 owning relation

- pure RED→GREEN：两个受审 index 的合法 current-schema/table owner 通过；错 schema 与错 table
  分别拒绝。
- PostgreSQL fixture 删除原两个 index，在临时表建立同名、同列、尽可能相同 predicate 的 unique
  index；collector 能收集这些错表对象，validator 输出两个对应 `0071.*` drift。
- fixture 的 `finally` 无条件删除伪 index/table 并重建原 index；恢复后完整 catalog 再次
  `ok=true`。PostgreSQL 专项 `24/24`，临时容器已清理。
