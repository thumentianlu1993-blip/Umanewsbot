# 历史赛历 Release B 设计

## 1. 当前结构与根因

Release A 已提供 nullable `edition_year`、public-path registry、target supersession、repair
receipt、maintenance gate 与只读/写入工具。当前仍有两个旧唯一约束把公开年误当身份年：

```text
RaceEvent:                 unique(race_series, year)
HistoricalRaceEventTarget unique(race_series, year)
```

v1 classifier 只看单个 mismatch event 是否已有相同 series/natural-year event 或 target；一旦
存在就统一标成 `canonicalize_duplicate`。生产数据实际是“重复边界 + 连续错位链 + 合法同年多届”，
所以逐 event classifier 无法生成安全 action。

## 2. 最小改动范围

Release B 只修改：

- `server/stable/models.py` 的两组约束；
- 新 migration `0071_historical_calendar_release_b.py`；
- 新的只读 `check_historical_calendar_release_b_schema` 管理命令及部署 preflight 挂接；
- `historical_race_calendar_integrity.py` 的 v2 prepare/load/apply/verifier/rollback 系列 action；
- 现有 repair 管理命令的 schema-version 拒绝与输出；
- 聚焦 SQLite/PostgreSQL 测试和五份 change 文档。

复用现有 `RaceEventProductCanonicalLink`、public-path registry、approval、receipt、maintenance
gate、advisory lock、controlled artifact read、no-replace rollback ledger 和 cache-on-commit；不新增
模型、Celery task、环境变量、依赖或公开页面。

## 3. 数据模型与 migration

### 3.1 Migration 顺序

`0071` 保持单一 leaf，并只执行：

1. 移除 `uq_race_event_series_year`；
2. 新增 `uq_race_event_series_edition` 条件唯一约束；
3. 移除 `uq_historical_target_series_year`；
4. 新增 `uq_hist_target_active_series_year` 条件唯一约束。

宿主部署流程先构建候选 Release B image，但保持现有 Release A web/worker/beat/race-live worker
全部原态运行；随后通过专用 wrapper 启动 `compose run --rm --no-deps` 受控 one-shot 候选容器，
调用只读 `check_historical_calendar_release_b_schema --direction=forward --json`。wrapper 必须绑定并
核对候选 commit、候选 image ID、当前数据库 migration leaf=`stable.0070_horse_identity_evidence_commit_receipt`
和目标数据库 identity，不复用旧 web 容器，也不启动候选常驻服务。命令输出 schema version、方向、
两组冲突 count、规范化 rows SHA、上述 identity 和 `ok`；数据库/模型/查询/identity 异常均非零退出。
只有 forward 结果证明 non-null `(series, edition_year)` 无重复，且现有 target 满足新 active unique，
宿主才可调用 `run_application_release.sh`，再进入停服务和 DDL。preflight 失败时该调用次数为零，旧
服务运行状态不变。迁移不更新业务行。真实 PostgreSQL 验收记录 preflight artifact、
`0070→0071→0070`、锁等待和执行时长。

### 3.2 兼容性

- `edition_year=NULL` 不进入新 unique，保留 Release A 兼容窗口。
- 正常 writer 仍通过 `validate_event_years()` 和 target/event clean 合同。
- Release B 回滚 migration 恢复旧约束前，必须运行同一命令的 `--direction=reverse`，精确证明：
  `(race_series, public year)` event 无重复，且全部 target（包括 superseded 审计行）的
  `(race_series, year)` 无重复；保存 count/rows SHA。receipt 为零或没有 v2 data apply 都不能替代
  这两组兼容性查询。B-only 普通写入造成任一冲突时必须保留 `0071` 兼容 schema，先恢复数据兼容
  或使用已验证备份，不得尝试反向 DDL。

## 4. v2 prepare

### 4.1 Series grouping

prepare 仍从全库 mismatch 开始，但先按 `race_series_id` 聚合；无 series 的行保持 event-level block。
每组一次读取：

- 全系列 events、targets、public paths、全部涉及该系列 event 的 canonical product links；
- 每个 event 的全部 reverse FK/O2O relation，但排除已归入 managed target/path 和 managed
  canonical-link ledger 的关系；immutable relation key 继续使用
  `model_label:accessor:field`；
- source refs、日期、等级、赛果/runner 的规范化身份摘要；
- scope 外会占用拟议 `(year, slug)` 的 event/path。

完整快照形成 `series_precondition_sha256`，action scope 按 series ID 排序生成。

### 4.2 Chain planner

planner 只生成候选，不自动批准：

1. 对相同 `series + local_date` 的 event 建立 duplicate group。
2. 只有来源身份、核心字段和 runner/result 规范化摘要完全等价时，才允许进入
   `duplicate_review_candidate`；否则 block。
3. 其余 event 按 local date、edition year、ID 构图，验证每个 event 只映射一个目标 edition。
4. 香港普通马季仅在已有权威分类证据下建议 `edition_year=local_date.year`。
5. 合法跨年届次保留 edition year；同一自然年多届时，plan 必须携带人工确认的唯一 slug。
6. 计算 target reassignment；每个 active target 最多一个 event，每个 event 最多一个 target。
7. 计算 path owner 轮转与 tombstone path；任何 scope 外占用即 block。

### 4.3 Reviewed overlay

prepare 输出 `review.template.json`，人工 overlay 至少填写：

- 每个 duplicate group 的 survivor/duplicate 与证据摘要；
- 每个 event 的 final public/edition year、slug、series、visibility；
- 每个 target 的 final event/resolution；
- 每个 path 的 final owner/kind；
- 每个 canonical product link 的 before/after source、canonical owner、active 状态与审计字段；
- 每个非零 dependency relation 的 policy。

第二次 `--prepare-reviewed` 只读取原 census + overlay，验证完整性并生成新的 v2 manifest/action
scope。v1 artifact、缺字段 overlay 或 overlay SHA 不得进入 apply。

## 5. 依赖策略

ledger 枚举必须形成三个互斥集合，并分别生成 before/expected-after SHA：

1. managed target/public-path；
2. managed canonical-product-link（同时覆盖 duplicate 与 canonical 两个反向方向）；
3. immutable reverse dependencies。

canonical link 的新建、复用、停用和拓扑变化只进入第二组；既有 source/duplicate link 漂移、链、
环、同一 duplicate 多 active link 或 scope 外 canonical owner 一律 block。它不得进入第三组的 retain
SHA，也不得因从 relation enumeration 排除而失去锁、precondition、verifier 或 rollback 覆盖。

第三组默认策略为 `retain_on_tombstone`，这是生产当前五类非零依赖最保守的处理：

- `RaceEventRunner`、`RaceEventResult`、`RaceEventDataCandidate`；
- `HorseP0Source.race_event`；
- `HorseIdentityConflict.race_event`。

retain 不改变依赖行，只把 duplicate 从产品可见范围排除，并通过
`RaceEventProductCanonicalLink` 保留审计关系。若 survivor 缺少数据，overlay 可以提出
`repoint` 或 `dedupe_exact`，但必须逐行绑定 before SHA、目标唯一键和回滚 payload；首版实现可
对这两种策略继续 block，不为完成率放宽。

未知新 relation 不在 manifest relation policy 集合中时，apply/verifier 立即失败。

## 6. 原子 apply

Release B 部署不调用 apply。后续获批 apply 的顺序为：

1. 验证 v2 manifest、review overlay、approval、action scope、actor、写总开关和 live gate。
2. 取得 manifest advisory lock；按 series ID、target ID、event ID、path ID、canonical-link ID
   固定顺序加行锁，并在锁后重算 precondition。
3. 预留 no-replace rollback ledger，保存所有将变更行的完整 payload。
4. 对每个 series 在同一外层事务中先把受控 canonical path 移到 manifest 固定的 tombstone key，
   再按 ledger 写最终 owner，避免中间唯一冲突。
5. 按 managed canonical-link ledger 建立/核对 link，并重验无链、无环和唯一 active source；
   duplicate event 解除 series、设 draft、写 tombstone slug。
6. 按 ledger 更新 survivor/chain event 的 public/edition year 与 target association/status。
7. 核对所有 retain dependency 行 SHA 未变；首版禁止无 ledger 的删除或 repoint。
8. 运行 series 守恒、全局 series/edition、target active unique、registry owner 与临时 key 零残留
   检查；创建 receipt 后提交。
9. `transaction.on_commit` 失效 public cache；独立 verifier 更新 receipt 状态。

任一 series 失败会回滚整批，不允许 14 个系列部分提交。maintenance exit 的锁顺序与 apply
统一为“全局 advisory → active gate → series rows”，并增加真实 PostgreSQL 并发测试，关闭
Release A 遗留的理论锁顺序 P2。

## 7. Verifier 与 rollback

Verifier 必须验证：

- 所有 `local_date` 非空 event 的 public year 正确；
- 非空 `(series, edition_year)` 全局唯一；
- 非 superseded target 的 `(series, year)` 唯一；
- target/event edition identity 一致；
- superseded target 指向同 series、同 edition/year identity 的 active survivor，且拓扑仅一层、无链环；
- 每个 published event 恰有一个 canonical path，所有 path owner 与 manifest 一致；
- duplicate tombstone 为 draft、无 series；managed canonical link before/after、唯一性与拓扑正确；
- retain dependency relation count/SHA 未变；
- 无临时 path/slug、无 scope 外变更。

Rollback 只接受 exact receipt + rollback ledger + 当前 post-state。它按相反数据顺序恢复，不执行
schema rollback；状态漂移时停止并保留生产备份恢复选项。

## 8. 性能与锁

- prepare 按 series 预取并以 chunk iterator 扫全库，禁止每 action 重扫全部模型。
- 生产量级当前为 9867 event、81 mismatch、14 series；测试声明 50k event/500 mismatch 的
  prepare 上限和查询数上限。
- migration 在应用服务停止的 release task 中执行；真实 PostgreSQL 记录 DDL 时间与锁。
- apply 锁范围只包含 manifest 的 series/event/target/path/dependency 行，但整批保持一个事务以
  防跨系列路径冲突和部分完成。

## 9. 可观测性

- summary 增加 series action、duplicate groups、chain length、cross-year、same-natural-year
  editions、dependency policy 与 blocker counts。
- receipt 继续是 exactly-once 权威；OperationLog 只记录摘要。
- 管理命令输出 schema version、manifest/action scope/review SHA、series/action/block 数。
- Release B 部署验收明确报告数据未变，不以 migration 成功冒充 81 条已修复。

## 10. 回滚与发布边界

- 本地实现：删除 Release B diff，不影响生产。
- Release B 关闭态部署失败：恢复冻结 Release A image；若 `0071` 已应用，只有 reverse preflight
  的两组旧约束兼容性查询通过并保存证据后，才可经审核反向 migration；否则保留兼容 schema
  回退代码。是否存在 receipt/data apply 不是充分条件。
- data apply 前：Release B schema 可长期保持，两个历史开关继续关闭。
- data apply 后：不得直接回退 `0071`，必须先执行 manifest-bound 数据 rollback/verifier 或恢复
  已验证备份。
- Release C 必须等待全库 verifier 为零 blocker，另建 change、review 和授权。
