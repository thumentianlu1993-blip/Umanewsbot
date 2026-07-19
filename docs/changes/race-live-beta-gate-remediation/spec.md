# 准实时公开 Beta 上线门禁修复规格

## 1. 背景

`2026-07-19` 生产 Free racecard proof 证明法国当日 15 场赛事中有 2 场存在
coupled entries：不同 `horse_id` 合法共享同一参赛编号。当前
`parse_the_racing_api_live_racecards_payload()` 把重复 `number` 视为整页非法，导致
event 733–735 prepare 返回 `racecard_schema_invalid`。

同一次代码层发布还确认 frozen-image rollback artifact 缺少受审 manifest 和进入四层
maintenance-off 的原子入口，原 Gate D 未完整满足。所有新地区、scheduler 和 monitor
当前均保持关闭。

## 2. 目标行为

### 2.1 Coupled entries

- 同一 racecard 中两个不同、非空 `horse_id` 可以拥有相同非空 `number`。
- 两条 runner 必须分别保留原 `horse_id`、`horse`、`number`、`draw` 和 jockey 字段；
  不把号码猜成 `1A/1B`，不合并 runner。
- 同一 racecard 的重复非空 `horse_id` 继续 fail-closed。
- 页内无关赛事的合法 coupled entries 不得使目标赛事 prepare 失败。
- 其他严格 JSON、race ID、runner 上限、必填字段和类型门禁不变。
- legacy `RaceEventRunner` 必须允许不同 external runner 共享号码，并以显式
  `external_runner_id` 作为 live 来源身份；同一 event 的非空 external ID 继续唯一。
- fresh initializer 遇到任何既有 legacy runner 必须拒绝，禁止与历史 importer 或人工行
  叠加；replay/verify 必须精确核对 runner 数量、external ID、号码、名称及无额外行。
- 没有 external ID 的历史 runner 保持兼容；仅按号码更新动态字段时，号码若匹配多行
  必须结合唯一 horse name，否则计为 ambiguous 并零写入，禁止 `.first()` 猜测。
- P0 马匹来源 participant key 对 live runner/result 统一使用
  `source_key + external_runner_id`；合法 coupled 同号码的两匹马必须把 runner 与
  result 一一配对，不得覆盖同一 active 来源，也不得让不同来源的相同 external ID
  落入同一身份空间。
- racecard refresh/replay 遇到 legacy runner 新列与
  `source_refs.external_runner_id` 都非空但不一致时，必须在 observation、tracking、
  runner、participant 和 revision 任一写入前拒绝整次更新。

### 2.2 Rollback bundle

- 新增只读生成器，从一个已公开 provisional event 的当前审计状态生成严格 rollback
  bundle；不得访问网络或写数据库。
- bundle 必须绑定：
  `reviewed_release_image_id`、filtered env SHA、event ID、current/provisional revision、
  publication、allowlist、tracking lock version，以及 global/region/source/event 四层
  policy 的 maintenance/restore 完整快照。
- maintenance 快照固定 `mode=off / version=current+1`；restore 快照保留当前 mode、
  digests 和 validity，且 `version=current+2`。source restore 必须为
  `provisional_public`，四层 restore 合成权限不得低于 provisional。
- 新增单事务 CAS maintenance 命令：在 scheduler/monitor=false、全库 active claim=0
  时，一次性把 bundle 中四层 policy 从生成时基线推进到 maintenance 快照。
- generator、dry-run 和 apply 都要求 `RACE_LIVE_ENABLED_REGIONS` 为空；目标 tracking
  必须为 `tracking_enabled=false`、`next_poll_at=null`、token/expiry 为空，且
  `lock_version` 与 manifest 一致。maintenance 不重新开启或改写 tracking。
- generator 必须在生成任何 artifact 前复用真实公共 read admission，确认目标当前可见、
  当前 revision 为同一 provisional；官方复核路线过期、observation/revision hash 漂移
  等会让页面不可见的状态必须拒绝。
- maintenance apply 任一基线漂移必须零写入；精确重放返回 already applied，不重复递增。
- 既有 frozen-image wrapper 的 `validate -> restore-policies-coarse -> validate ->
  restore-policy-event` 必须可使用该 bundle 完成只读验证和分层恢复。
- validator 和 restore 必须要求 scheduler/monitor=false、enabled regions 为空，并在
  任一 policy 恢复写入前对 manifest 冻结的 current revision pointer 做行锁内 CAS；
  maintenance 或 coarse-restored 阶段发生 pointer 漂移时，整阶段零写入。
- artifact root 必须是真实 `0700` 目录；最终文件 root-owned `0600`、非 symlink、
  最大 1 MiB、原子发布、不可覆盖，不包含来源、SMTP、通知或数据库 secret。
- restore 阶段机只允许：
  `all maintenance -> coarse restore + event maintenance -> all restore`；
  coarse/event 精确 replay 为零写，event-before-coarse 必须拒绝。任一步失败时必须按
  实际阶段 handoff，不得笼统声称“四层仍 off”。

## 3. 非目标

- 不改变 results parser、runner/result 状态机、publication admission 或前台文案。
- 不改 participant/revision/result schema；legacy `RaceEventRunner` 允许增加最小身份字段、
  替换唯一约束并提供旧行兼容。
- 不扩大 enabled regions、scheduler、monitor、event allowlist 或公开范围。
- 不在本 change 中把法国 event 直接 promotion；修复发布后只恢复 prepare/shadow 门禁。
- 不把当前缺失的历史 Gate D 事实改写为已满足；本 change 只让下一次冻结发布按门禁执行。

## 4. 验收标准

- 法国真实结构的离线最小 fixture 可解析 coupled entries，两个 runner 均保留。
- PostgreSQL initializer/refresh 能分别保存两个 participant、source identity、
  revision item 和 legacy runner；同号码 runner/result 按来源外部身份正确配对，
  动态字段或 legacy identity 歧义不会误写。
- 重复 `horse_id`、字段非法和超限仍拒绝。
- 无关 coupled race + 普通目标 race 的整页 prepare 能形成 manifest。
- rollback bundle 生成、maintenance dry-run/apply/replay、只读 validator、coarse/event
  restore、current revision CAS 和 event 924 read gate 在 PostgreSQL 生产形状测试
  通过。
- 等待中的 direct claim、due selector 与 policy CAS 在 maintenance 成功后均不能产生
  claim 或部分写入；enabled regions 非空时零 artifact、零数据库写入。
- 无 migration drift；准实时相关 SQLite、PostgreSQL、Django、Compose 和镜像合约回归
  通过。
- 生产发布前取得新冻结 fingerprint 的成功 review 和用户授权。
