# lifecycle enforce canary 设计

## 现状与根因

生命周期决策与 `_apply_enforce` 已存在，但当前生产防护形成两道有效上限：

1. `deploy/switch_lifecycle_mode.sh` 只接受 `false/off` 与 `true/shadow`；
2. event 186/187 的 `RaceEventLifecycleControl.mode` 是 `shadow`，全局 mode 即使变为 enforce，
   `_effective_mode()` 仍返回 shadow。

因此本 change 不重写状态机，只补齐“受审 control 提升 + 受审全局启用 + 运行时证据复核”。

## Canary manifest

新增 schema v1，采用现有 enrollment 的安全文件读取、canonical JSON、raw/content SHA、Git OID、
大小上限和原子 artifact 发布实现。生产 manifest 必须由当前数据库只读 prepare 生成，包含：

- 顶层：`schema_version`、`generated_at`、`apply_expires_at`、`runtime_valid_until`、
  `approved_commit`、`mode=enforce`、
  `source_enrollment_manifest_sha256`、`events`、`content_sha256`；
- 每场：event ID/updated_at/status/visibility/region/timezone/local date/race datetime；
- control mode/updated_at/schedule generation/next refresh/enrollment SHA/manifest_data SHA；
- 冻结 `enrollment_schedule_hash`、目标 mode 与 expected current mode。

解析器要求恰好两个正整数且不重复的 event ID、规范字节完全一致、所有未知字段拒绝。所有赛事必须有
aware `race_datetime`。`apply_expires_at=generated_at+24h` 只约束 prepare→apply 的新鲜度；
`runtime_valid_until=max(race_datetime)+30m+24h` 覆盖最晚 T+30 与一天观察余量。apply 后 runtime 不因
短期 apply 窗口到期而停止，但超过 `runtime_valid_until` 必须 fail closed 并要求切回 off/shadow。
实现不硬编码 186/187；生产 G3 授权必须绑定 manifest raw SHA，并由启用脚本参数再次要求精确
`EXPECTED_CANARY_EVENT_IDS=186,187`。promotion 与 verify 管理命令还必须接收独立
`--expected-event-ids`，并在任何数据库写入前确认其与 manifest 内有序 ID 完全一致；宿主 wrapper
必须把同一授权值传入容器，不能只校验环境变量本身。

## 关闭态 apply

新管理命令提供 dry-run/`--apply --confirm-enforce-canary`，生产只允许由
`deploy/promote_lifecycle_enforce_canary.sh` 调用。wrapper 取得共享部署锁，在同一锁区内先后验证宿主
web/worker/Beat 均为真实 `false/off`，再执行一次 one-shot/exec apply，最后复核仍为 false/off。

服务内部：

1. 解析并验证 artifact；校验 expected commit；
2. 强制 settings 为严格 `false/off`；
3. `transaction.atomic()` 内先取得固定 PostgreSQL advisory transaction lock，再按 ID 排序
   `select_for_update` 锁 event/control；SQLite 测试使用进程内等效锁，生产 PostgreSQL 不降级；
4. 重新计算全部冻结字段并确认没有 claim、manual pause 或范围外 enforce control；
5. 两条 control 一次性改为 enforce，并把 canary raw/content SHA、approved commit、applied_at 写入
   既有 `manifest_data.enforce_canary`，其精确初始形状为：
   `schema_version=1`、raw/content SHA、相同有序 event IDs、approved commit、runtime_valid_until、
   `activation_state="inactive"`、`activation_id=""`、`activated_at=null`；
6. 同事务写 `OperationLog(action_type=lifecycle_enforce_canary_applied)`，detail 使用 canonical JSON；
7. 同 SHA 重放要求数据库结果逐字节一致并零写；部分写入或不同 canary 冲突 fail closed。

不新增 migration。冻结 artifact 是 promotion 的外部信任根；control `manifest_data` 是运行证据；
OperationLog 是二级 receipt，不宣称不可变或唯一权威；真正状态变化继续由 append-only applied
transition 审计。`manifest_data.enforce_canary` 不再满足原 shadow enrollment 的逐字节 replay，延期/
改时或退出 canary 必须走后续受审 rotation，不允许直接重放旧 enrollment manifest。

## 运行时门禁

新增严格 settings：`RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_SHA256` 与
`RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_EVENT_IDS`。canonical/active env 各键恰好一次；runtime coherence
核对 web/worker/Beat 三服务值、预期值和当前 revision 一致。false/off 与 true/shadow 时两个键必须为空，
且止损路径不读取 manifest 文件。

为兼容首次发布前尚无两项新键的旧 `false/off` resident，严格关闭态 coherence 允许 canary 键
“不存在”或“恰好一次且为空”，两者安全语义等价；重复键、非空值或任何非 `false/off` 模式仍严格
要求恰好一次并逐值匹配。mode switch 重写并重建后会把两项空键正式补齐。

`apply_race_lifecycle_decision()` 在有效模式为 enforce 时同时校验独立 settings 参数与 control：

- control `manifest_data.enforce_canary` 必须结构合法；
- 未超过 `runtime_valid_until`、approved commit/SHA 合法；
- event ID 必须同时包含在 settings event IDs 与冻结 event IDs，两个集合必须逐字节等价；
- 当前 schedule generation、enrollment SHA 与 schedule hash 必须匹配；
- settings/任务握手传入的 expected canary raw SHA 必须匹配；
- 当前 event 仍 published、无 manual pause，状态仍可由现有单向规则推进。

scanner dispatch 在全局 enforce 时只从 settings 取得 expected SHA/IDs，并在 claim 前验证两条目标
control 已由同 SHA 原子激活：两条均为 `activation_state="active"`，且共享同一非空 64 位
`activation_id` 与同一 `activated_at`；advance task 传递该独立握手，并在事务内从 settings 重新读取后
传入 apply。promotion 后的 `inactive` control 在 global enforce 下必须零 claim、零 applied。
范围外 control 即使携带自洽伪造 evidence 也只能按其 shadow mode proposal；若被错误设为 enforce，
scanner 的同一 claim 查询必须排除该范围外 enforce control，做到零 claim、零 dispatch、零周期性 TTL
重试；范围外 shadow control 仍可 claim 并产生 proposal。缺失、畸形或不一致均不 claim/不写 event。
全局 shadow 路径不要求 canary，避免破坏现有 observation。

## 模式切换

扩展 `switch_lifecycle_mode.sh`：

- 新目标 `true/enforce` 必须额外提供 manifest 文件、raw SHA、`EXPECTED_CANARY_EVENT_IDS`，并将
  SHA/IDs 写入两份 env；
- host 先以 no-follow、regular-file、1 MiB 上限读取 manifest 并核对 raw SHA；所有容器命令均通过
  `compose exec -T web ... --manifest-stdin < "$MANIFEST_FILE"` 传入原始字节，不依赖 host path mount
  或 `docker cp`。容器 stdin loader 拒绝空/截断/超限/额外字节，重做 canonical、raw/content SHA、
  expected commit 与 schema 校验；每次都绑定同一 host expected raw SHA；
- 在共享部署锁内、任何 Beat/env/container mutation 前，通过当前健康 web 执行只读 verifier，确认
  当前严格 false/off、代码 OID、两条 enforce control 与 manifest 完全一致、范围外 enforce=0；若是
  同 manifest 的旧 active canary，先在 advisory lock 内 CAS 回 inactive，确保每次 enable 都重新激活；
- stop Beat 后重写 env，只先重建 web；DB verifier 通过后才重建 worker；
- worker 启动后核对 web/worker runtime coherence，但 scanner/apply 仍因 control inactive 而 fail closed；
- 在同一部署锁内，以同一 stdin manifest和固定 advisory transaction lock 重新执行完整 DB verifier、
  范围外 enforce=0、两条 control/event/claim/pause/visibility 漂移检查，然后用 CAS 将两条
  `inactive→active`，生成并共享同一个随机 64 位 activation ID；同 manifest active 重放只有在两条
  evidence 完全一致时零写成功；部分 active、不同 activation ID 或不同 manifest 一律拒绝；
- activation 后再次只读验证 active cohort，再启动 Beat，最后核对三服务；
- `false/off` 不要求 canary 参数，确保紧急停用不被 artifact 可用性阻塞；失败恢复仍只收敛到 off。

脚本不会手工执行 scanner，也不会启动 race-live。唯一成功顺序固定为 activation/active verify 后启动
Beat；上线验收观察第一个正常 Beat scanner tick，不在 Beat 启动前另造一条 smoke 调度路径。

## 并发、缓存与幂等

- promotion 以全局 advisory xact lock + control/event 行锁串行；scanner claim 活跃时 promotion 拒绝。
- 状态 apply 延用 transition dedupe key，重复投递只产生一次 applied。
- `RaceEvent.status` 更新延用现有缓存失效路径，并新增 canary 回归断言。
- promotion/activation 重放不改变 `updated_at`、不新增 OperationLog。
- 切回 off 后复用同一 manifest 重新激活时，允许已由本 lifecycle 合法产生的
  `scheduled→running→finished`、`event/control.updated_at`、`next_refresh_at` 与 claim generation 变化；
  schedule/generation/enrollment/cohort/authority/visibility/人工锁暂停仍冻结，任何未清 claim 或非法状态
  仍 fail closed。每条 canary applied transition 都写入精确 manifest raw/content SHA、event IDs、commit
  与当次 activation ID；重新激活时必须验证本 generation 的 applied 链、reason、T/T+30 时间边界和该
  provenance，外部直接改状态或普通 lifecycle transition 均不能冒充。每次重新激活生成新的 activation
  ID，旧激活不能泄漏到下一轮。
- 批量范围固定两场；查询和内存均有硬上限，不引入全表高频扫描。

## 回滚

一级止损：受审 mode switch 立即切 `false/off`，停止 Beat、重建 web/worker、验证一致后再恢复 Beat；
已排队任务受现有 runtime handshake 与事务内开关复核阻止。

二级观察：如需恢复 shadow，先保持 false/off，再切 `true/shadow`；全局 shadow 会把两条 enforce control
压回 proposal 行为。control 内 canary 证据不删除，便于审计和后续受审复用。已发生的合法公开状态不
自动回退；需要业务纠正时另建 manifest-bound 数据修复，不在本 change 猜测反向状态。
