# 赛事总账与公开赛程关联设计

## 最小模型方案

不新增数据库字段或迁移。现有 `HistoricalRaceEventTarget.event`、`RaceEvent.race_series/year/status/result_confirmed_at` 足够表达 `not_due + scheduled event`。保留数据库对 `not_due + imported` 的禁止约束。

## 领域服务

新增独立 reconciliation 服务，职责为：

- 生成逐目标只读分类和版本化三层覆盖报告。
- 在事务中锁定目标，重新计算目标与赛事 identity，确认与审批 artifact 一致后关联。
- 只采用同系列同年度的唯一既有赛事。
- 记录 `OperationLog` 和 rollback ledger，不修改其他字段。

历史物化服务继续负责已到期目标创建历史赛事；它仍不为 `not_due` 创建赛事。现有赛事导入命令改为调用共享的“采用既有赛事”判断，避免把同系列同年度的赛程误报为冲突。

## Artifact

一次 dry-run 目录包含：

- `reconciliation.jsonl`：逐目标分类、before identity、candidate event identity。
- `coverage_report.json`：schema version、as-of、三层分母及分组统计。
- `review.csv` 与 `review.html`：冲突和缺失项。
- `manifest.json`：参数、文件 SHA、目标 ID 集合、数据库只读基线计数。
- `approval.json`：独立审批产物，包含 `status=approved`、审批人、审批时间和精确 manifest SHA。
- `rollback.jsonl`：apply 时生成，保存目标旧 event_id 和写后 identity。

manifest 使用原始字节 SHA-256 绑定；产物先写临时目录，再原子发布到不存在的最终目录，最终目录拒绝覆盖。manifest 的 artifact key 必须与同名规范相对路径精确绑定且路径唯一。manifest、approval、reconciliation 和 rollback ledger 均拒绝符号链接；每个输入只安全打开一次，同一份 bytes 同时用于 hash、解析和执行，避免二次打开的 TOCTOU。apply 要求显式传入 expected manifest SHA 与 expected approval SHA，并复核 approval 中绑定的是同一 manifest；任何自签、缺字段或漂移都拒绝写入。

## Apply 与并发

- export 在一个一致数据库事务快照中生成分类、报告和 baseline，并验证 manifest target 数、历史/当前报告分母和 baseline target_count 守恒，不依赖停止 runner。
- apply 在任何数据库写入前预占不可覆盖的 rollback ledger 临时文件；整批目标在单一 `transaction.atomic()` 中按目标锁定并串行处理。
- apply 前再次核对 target/event identity、关联空值和状态兼容性。
- `already_linked` 视为幂等成功；漂移则 fail closed。
- 不创建、不删除 `RaceEvent`；不改目标和赛事的其他字段。
- ledger 在事务提交前完成 fsync 和不可覆盖原子发布；发布或事务提交失败时整批数据库写入回滚，并清理已发布 ledger，禁止出现“关联成功但无 ledger”。

## 回滚

只允许解除本次新增、且写后 target/event identity 未变化的关联。rollback 先在固定顺序下锁定并校验 ledger 涉及的全部目标和赛事，再在同一事务中解除全部关联；任一后段漂移都会使整批零部分回滚。若关联后目标已推进状态或赛事已写入新详情，回滚拒绝执行，改为人工补偿或数据库恢复。任何回滚都不删除赛事、出马表或赛果。

## 后续边界

准实时状态机和赛后抓取在关联修复验收后另行实现。本期报告仅在目标 `module_statuses.results=complete`、赛事 `finished`、`result_confirmed_at` 非空且全部结果 `is_confirmed=true` 时判定赛果完整；单独存在结果行或旧数据缺少任一审计证据时不算完整。

## 管理命令

统一入口为 `reconcile_race_event_coverage`：

- 默认模式只生成新 artifact，必须提供不存在的 `--output-dir`。
- `--verify` 只读复核 manifest 与数据库守恒。
- `--commit` 才执行关联写入，并强制要求 `--expected-manifest-sha256`、独立 `--approval` 和 `--expected-approval-sha256`。
- `--rollback` 还必须提供 rollback ledger 及其精确 SHA-256；任何目标、赛事或赛事详情漂移都会拒绝解除关联。

命令不负责创建批准；dry-run 只生成 `status=pending` 的 `approval.json` 模板，批准人必须独立填写并重新计算 approval SHA-256。
