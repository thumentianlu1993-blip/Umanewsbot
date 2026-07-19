# 准实时公开 Beta 上线门禁修复设计

## 1. Coupled entries 解析

parser 改动限定在 `server/stable/services/race_live_fixtures.py`：

- 保留 race 级 `race_id` 唯一；
- 保留每场 `external_runner_id` 唯一；
- 删除 runner `number` 唯一约束；
- 继续把原号码作为展示/来源事实，不产生派生号码。

participant/revision/result 身份继续以
`source_identity + external_runner_id` 和 participant `stable_key` 为准。legacy
`RaceEventRunner` 当前仍有 `event + horse_number` 条件唯一约束，因此增加 migration：

- 新增 `external_runner_id = CharField(max_length=128, blank=True, default="")`；
- 删除 `uq_race_runner_event_no`；
- 新增 `event + external_runner_id` 非空条件唯一约束；
- 既有约 `100,132` 条 production legacy rows 当前均无 source external ID，migration
  不扫描/猜测 JSON，不做大表 backfill；新 live 写入填充新列；
- refresh 若遇到旧版本已在 `source_refs.external_runner_id` 留下身份的行，只在精确唯一
  命中时惰性写入新列；多行命中 fail-closed。

`update_runner_dynamic_fields()` 的选择顺序改为：

1. 输入有 external runner ID：只按新列或唯一 legacy source-ref 身份匹配；
2. 无 external ID：号码命中恰一行才使用；
3. 号码命中多行：仅在 horse name 于该集合内恰一行时使用；
4. 无号码命中时，horse name 在全 event 恰一行才使用；
5. 其余返回 `skipped_ambiguous`，不更新任何 runner。

历史 importer 继续创建 `external_runner_id=""` 的 legacy rows，不受新约束影响。
live initializer 的 fresh 路径只接受 legacy runner 零行；已有历史/人工 runner 时整场
fail-closed，不尝试猜测合并。已初始化 event 的 replay/verify 精确核对 materialized
runner 数量、顺序、external ID、号码、名称和 source refs，任何删除、篡改或额外行均拒绝。
P0 horse source 的 participant key 对非空 external runner ID 使用来源命名空间和 ID 的
稳定 identity digest；命名空间优先读取 `source_key`，runner/result 的
`source_refs`、`raw_payload` 与 runner 新列统一参与配对。只有空 external ID 的旧行
继续使用号码/名称兼容路径。racecard refresh/replay 在写 observation 前扫描全部
legacy runner；新列与 `source_refs.external_runner_id` 都非空但不一致时整次拒绝，
避免错误身份在 replay 路径被惰性固化。

## 2. Rollback bundle 结构

新增服务与 management commands：

- `prepare_race_live_rollback_bundle`
- `transition_race_live_rollback_maintenance`

生成器输入：

```text
--event-id
--reviewed-release-image-id sha256:<64hex>
--filtered-env-sha256 <64hex>
--approved-commit <40hex>
--run-id
--output-root <absolute 0700 dir>
```

最终目录包含：

- `manifest.json`
- `report.json`
- `sha256s.json`

manifest 复用既有 wrapper 所需顶层字段，并增加 `approved_commit`、`generated_at`、
`baseline_policies`、`expected_tracking_state` 和 `maintenance_confirmation`。manifest
和所有嵌套对象使用 exact-key schema；读取拒绝 duplicate JSON key。既有 commands
只消费它们已有的严格字段；新增 maintenance command 严格校验完整 schema 和 SHA。
生成的 manifest 必须包含 `expected_current_revision_id`；validator 与 restore command
必须显式透传，禁止只验证 dedicated provisional pointer 而忽略当前公开 pointer。

## 3. 生成时门禁

生成器在同一只读快照中确认：

- scheduler/monitor 均为 false；
- `RACE_LIVE_ENABLED_REGIONS` 精确为空；
- 全库 active claim 为 0；
- event、control、tracking、current revision、dedicated provisional revision、
  observation/source、allowlist、publication 和四层 policy 齐全；
- current revision 等于 dedicated provisional revision，phase 为 provisional；
- publication/allowlist/source digest 与 version 一致；
- 四层当前 mode 至少形成 provisional public，source 恰为 provisional；
- validity 均晚于当前时间；
- current policy version 可安全生成 `+1/+2`。
- target tracking 精确为 `tracking_enabled=false`、`next_poll_at=null`、
  `active_attempt_token=""`、`claim_expires_at=null`，并绑定 lock version。
- `resolve_race_live_public_read()` 返回 visible，revision ID 与 dedicated provisional
  pointer 一致且 phase 为 provisional；route validity、observation/revision hash 等真实
  read admission 任一失败即拒绝。

生成器不修改 policy，不把 payload、secret 或环境值写入 artifact。

## 4. Maintenance CAS

`transition_race_live_rollback_maintenance` 支持：

```text
--manifest
--expected-manifest-sha256
--expected-approved-commit
[--apply --confirm ENTER_RACE_LIVE_ROLLBACK_MAINTENANCE_<event_id>]
```

dry-run 复核全部基线。apply 在单事务中：

1. 锁全部 projection control 和 tracking 行，确认 active claim=0；
2. 锁目标 event/control/tracking/revision/publication/allowlist/source；
3. 重新确认 settings enabled regions 为空，目标 tracking 全关字段和 lock version
   与 manifest 一致；等待中的 direct claim 提交后会看到 tracking disabled，
   due-selector 会因 locked/disabled 跳过；
4. 锁四层 policy，逐字段匹配 baseline/restore 前状态；
5. 一次性写入四层 maintenance snapshot；
6. 写一条不含 secret 的 OperationLog；
7. 事务内复核 read gate 已隐藏。

四层已精确处于 maintenance 时返回 `already_maintenance`，不写 OperationLog、不递增。
任一 scope 漂移或部分 maintenance 均整体拒绝。

## 5. Artifact 安全发布

- generator 必须以 root EUID 运行；artifact root/final/staging 的 `st_uid=0`、
  `st_gid=0`，root 为真实 `0700` 目录且祖先无不允许的 symlink。
- 以 `lstat -> O_NOFOLLOW open -> fstat identity` 读取输入；manifest/report/sha256s
  在同一 artifact root 下的随机 staging 目录生成。
- 三个文件均以 `O_CREAT|O_EXCL` 创建为 `0600`，写后 file fsync；staging 目录 fsync。
- 使用不可覆盖的 final-dir 发布；final 目录 fsync 后再 fsync artifact root。任何失败
  只删除本次 inode identity 匹配的 staging/final，不覆盖同名 run。
- final 目录 `0700`，三文件 root-owned `0600` regular non-symlink；每个最大 1 MiB。
- manifest/report 的递归 key/value 扫描禁止 secret key 名、credential 值和环境值；
  `sha256s.json` 只含文件名和 digest。

## 6. 恢复阶段机与演练

生产候选镜像生成 bundle 后，先将四层进入 maintenance，再用绑定的完整 image ID、
filtered env SHA 和 manifest SHA 执行：

```text
validate
restore-policies-coarse
validate
restore-policy-event
```

第一个 validator 必须在 PostgreSQL read-only transaction 中退出 0；coarse 恢复后
event 仍 off；第二个 validator 退出 0；event 恢复后 event 924 无缓存 read gate 显示
原 provisional revision。当前结果本身已是 provisional，故本次演练不执行
`restore-result` 写入；其既有合约测试继续回归。

validator 与 restore service 都要求 scheduler/monitor=false、enabled regions 为空。
restore 在锁定 publication control 后、任何 policy 写入前比较
`expected_current_revision_id`；maintenance 后或 coarse restore 后发生 pointer 漂移，
均返回 `current_result_pointer_changed` 并保持本阶段 policy 原样。

合法阶段和唯一下一步：

| 当前阶段 | 四层状态 | 允许命令 |
| --- | --- | --- |
| maintenance | 四层 maintenance | `validate`，随后 `restore-policies-coarse` |
| coarse-restored | global/region/source restore，event maintenance | `validate`，随后 `restore-policy-event` |
| restored | 四层 restore | `validate` 或精确 replay（零写） |

`restore-policy-event` 在 coarse 前必须拒绝且零写；coarse/event replay 必须返回已完成。
第二次 validate 失败时 event gate 仍隐藏，记录当前为 coarse-restored；修复外部漂移后只从
该阶段重跑 validate，再执行 event restore。不得回报“四层仍 maintenance”。

## 7. 发布边界

- 本地实现不访问生产网络/数据库。
- 生产 bundle 生成、maintenance apply、one-shot 验证/恢复和镜像切换必须在成功代码
  review 后取得新冻结版本授权。
- 生产全过程保持 scheduler/monitor false、enabled regions 为空。
- migration 为旧 image 兼容：旧代码容忍新增列和约束删除；若 hotfix 后已产生 coupled
  legacy rows，代码回滚必须保持对应地区/event tracking 关闭，禁止旧版动态更新器处理
  这些 event；需要完全撤销时使用切换前数据库备份，不手工合并 runner。
- 法国修复只先重新 prepare；完成后才单 artifact initializer
  dry-run/apply/verify/replay，仍保持 shadow。
