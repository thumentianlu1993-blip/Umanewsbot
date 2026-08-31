# TRA 多年四地区生产 apply 缺口审计

日期：2026-08-30（Asia/Shanghai）
状态：三项代码门禁均已本地实现并回归；最终 release/现场授权仍未就绪
副作用：0 TRA 请求、0 生产数据库写入、0 服务或配置变更

## 结论

现有共享 P0 写链已经能接收本 change 的 reviewed research。此前确认的 exact package、独立
profile/career apply ledger/reverse、maintenance preflight 三项代码缺口均已在当前 worktree 关闭，并通过
SQLite 与真实 PostgreSQL 16 回归。当前仍不能直接执行多年四地区全量生产 apply：尚缺独立全 diff 审查、最终
commit/image/release 身份、custom-format 写前备份、现场 fresh proof、用户精确授权和逐批生产 verifier。

identity review 是另一条已经闭环的窄链：它有 receipt、verify、零写 replay、after-state 漂移阻断和 exact
reverse。不得把 identity receipt 当成 profile/career 多表 apply 的 receipt 或回滚证明。

## 已有证据

### Reviewed release 与输入冻结

- release manifest 与 final artifact 逐字 SHA 绑定；rolling v2 还绑定 release candidate、batch manifest、
  combined candidates、append-only approvals ledger 和 supersede 状态；
- artifact、release、candidate 与三类输入使用单次 regular-file 读取，拒绝 symlink、路径逃逸、SHA 漂移和
  reviewer/binding 漂移；
- commit 只接受 v2 release 与显式 `--confirm-reviewed-artifact`；v1 只读；
- `write_prepared_artifact_directory` 使用新目录与原子发布，拒绝覆盖既有目录；本轮升级为 package v2，
  manifest 绑定 artifact relative path、size 与 SHA。

rolling approval parent 会合法保留多轮 candidate/release，不能把整个 parent 当作单包。本轮改为每个 commit
artifact 独占 `commit_package_<region>_<artifact_sha>/`，目录只允许
`reviewed_p0_horse_completion_artifact.json + manifest.json` 两个普通文件；release candidate v2 再绑定
manifest SHA。校验拒绝 package 路径逃逸、package/member symlink、非普通成员、缺文件、extra file、size/SHA/
payload 漂移。规格 I02 的 artifact package 部分现已满足。

专项测试新增 prepare package v2 的 exact member/size/SHA 断言、extra member 与 symlink 拒绝，以及 release
approval 在 extra member 存在时失败关闭。`stable.test_p0_horse_production_apply +
stable.test_p0_horse_completion_batch` 共 `255/255` 通过；首次完整回归发现 macOS `/var` 与
`/private/var` 的父路径等价问题，现先拒绝 package 自身 symlink，再用解析后路径做 containment 比较，重跑全绿。
之后新建自有、临时、`--rm` 的 PostgreSQL 16 容器重跑专用锁/rollback `8/8`，完成后停止并确认容器 absent。

### Dry-run、幂等与事务

- dry-run 运行 artifact/release/current snapshot 校验与 `_simulate`，并有业务表零写断言；
- commit 使用 identity advisory/session lock、PostgreSQL table lock、单事务和 locked identity rescan；
- SQLite 测试覆盖中途异常整批 rollback、重复 artifact 幂等、manual lock/人工字段不覆盖；
- PostgreSQL 专用测试文件覆盖 table-lock 顺序、非协作插入等待、lock timeout 回滚、同 artifact 并发单身份、
  业务异常和 task-log 后异常整批 rollback。

当前本机 SQLite 测试命令共发现 58 项，50 项通过、8 项 PostgreSQL 专用用例因 backend 非 PostgreSQL 跳过。
随后另起隔离 `postgres:16` 临时容器运行这 8 项：首次为 `3/8`，5 项暴露专用测试仍把 legacy v1 release
fixture 直接送入已经只接受 v2 的 commit gate。测试现显式从“已验证 v2 release identity”之后进入数据库窗口，
release candidate/rolling ledger 仍由既有独立合同测试负责；修正后 PostgreSQL `8/8` 通过。临时容器已停止并
自动删除，没有复用或修改其他任务的数据库容器。

### Execution、identity 与 profile/career ledger

- TRA 网络 execution ledger 已有连续 ordinal、唯一 claim、30 分钟间隔、累计 request budget、safe-stop 后 fresh
  G3/retry 和 completed artifact 重验；targeted batch resume 对已完成 artifact 为零请求；
- identity review receipt 已有 apply/verify/replay/reverse，并在 after-state 漂移时拒绝 reverse。
- profile/career 现有独立 `apply_plan_id + source_batch_id + region + ordinal` ledger：唯一 active claim、连续
  ordinal、失败后 exact resume、completed receipt replay 零写；receipt 与业务写同事务，保存受影响 scope 的
  exact before/after，并拒绝删除未捕获的后来关联行。
- apply/reverse receipt 为模型级不可变，Django admin 只读且不展示 claim token/大状态快照；reverse 默认关闭，
  必须绑定完整批次身份与 state SHA，after-state 漂移即整批零写失败。
- production apply 采用 database-only policy，不自动发布页面、QQ、邮件或 race-live；direct legacy commit 在
  production preflight 默认开启时被拒绝，不能绕过 rolling ordinal/receipt。

网络 execution ledger、identity receipt 与 profile/career receipt 继续职责分离，不能互相替代。

### Maintenance preflight

- host + Django proof 在同一 deployment lock 原 token 连续窗口绑定 artifact/package/release/candidate、
  apply plan/source batch/ordinal、revision/image、DB identity、migration leaves 与 lock metadata；最长 5 分钟；
- 逐项阻断 10 个同步开关、race-live 调度开关、active import/lock、completion/apply/history claims、started
  task、非 idle/partial Celery、`celery`/`race_sync_v2` 非零；`race_live` 只比较守恒，不消费；
- inner wrapper 只验证并消费外层已持有的锁，不 acquire/release、不 stop/start；proof 生成、claim 前、dry-run
  前、commit 前及结束后均有边界复核。

## 仍未完成的发布门禁

1. 完成只读独立全 diff 审查并关闭 findings；
2. 固化最终 commit、image、migration、artifact/package/release/preflight 命令与回滚的 G2 包；
3. 在每个最终 release 上重跑 SQLite 全套和 PostgreSQL 专用 9 项；当前 worktree 为 `288/288 + 9/9`，但不
   替代最终 release/image 身份；
4. 赛事阶段明确重开且生产容量门禁通过后，取得逐批精确授权；同锁窗口完成 custom-format backup、fresh
   preflight、commit、receipt verifier 和页面只读抽检。任何失败 safe-stop，只能从最后 completed receipt 续跑。

上述发布门禁关闭前，可以继续零写网络导出、离线物化、identity/module review 和 production dry-run；不得执行
canonical profile/career commit，也不得把 staging/identity apply 误报为“全部数据已落表”。
