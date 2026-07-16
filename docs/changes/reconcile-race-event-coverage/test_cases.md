# 测试用例

## P0 领域行为

- `not_due` 可关联唯一的 scheduled event，目标状态保持不变。
- `not_due` 不得变为 imported，历史物化器不得创建未来 event。
- 同系列同年度唯一候选可关联，重复执行不产生变化。
- 同名异系列、一对多、多对一和状态冲突不写入。
- `not_held` 不关联任何 event。
- 目标、赛事或系列地区/年份不一致时拒绝。

## P0 报告

- 历史分母截至 2024，当前分母从 2025 开始。
- 展示扩展赛事不改变正式分母。
- 取消和延期不进入赛果缺失率。
- 宽限期内进入 grace，宽限期后无赛果进入 awaiting result。
- 只有 `finished + imported + module_statuses.results=complete + result_confirmed_at + 全部结果 is_confirmed` 计为完整。
- 单独存在结果行、部分结果或缺少确认时间的旧数据不得计为完整。
- 三层分母和各分类数量分别守恒。
- 赛果候选全集中的 future、grace、cancelled、postponed、complete、incomplete、awaiting_result 必须各且仅出现一次。

## P0 Artifact 与写入

- manifest 任一字节变化都会阻止 apply。
- approval 必须独立绑定精确 manifest SHA；缺审批人/时间、manifest 不一致或 approval SHA 漂移都会阻止 apply。
- 最终 artifact 目录拒绝覆盖，生成过程通过临时目录原子发布。
- apply 前 target/event identity 漂移会阻止写入。
- dry-run 不写数据库，apply 只写 event_id 和 OperationLog。
- verifier 证明 target/event/detail/publication 数量守恒。
- rollback 只解除未发生后续变化的本次关联。
- rollback ledger 已存在、父路径不可发布或原子发布失败时不产生任何关联；多行 rollback 后段漂移时零部分解除。
- manifest/approval/reconciliation 的符号链接被拒绝；验证后替换路径内容不改变本次执行使用的已验证 bytes。
- manifest artifact key 只能绑定同名规范唯一路径。
- 采用既有赛事时只新增缺失 alias，不覆盖既有人工 alias 元数据；导入统计分别报告 created/adopted。

## 回归案例

- 2026 东海锦标目标关联现有东海锦标赛程，不误连金鯱赏。
- 2026-07-18 至 2026-07-31 的公开赛程可以全部出现在 calendar 层，但只有正式目标进入 current 分母。
- 现有历史 `8032` 账本统计语义不被旧命令静默改变。

## 本地验证证据

- 原始 RED：`server/stable/test_race_event_coverage_reconciliation.py` 在实现前因 service API 缺失失败；首次命令还确认本机无 Python/Django 环境，随后统一使用现有 ARM64 Django 镜像和内存 SQLite 执行。
- GREEN：聚焦 reconciliation、报告、artifact、双 SHA、apply/verifier/rollback 及首次 reviewer 回归共 `22/22`。
- 相关回归：`stable.test_current_year_race_apply_descriptor`、`stable.test_historical_race_batches` 与聚焦测试合计 `100/100`。
- 旧失败：`RaceEventPageMVPTests.test_csv_import_candidate_fetch_and_candidate_apply` 的测试夹具改用既有门禁允许的 2025 年，单测 `1/1` 通过；生产 current-year 门禁未放宽。
- Django：`check` 通过；`makemigrations --check --dry-run` 为 `No changes detected`。
- 静态检查：受影响 Python 文件 `py_compile` 通过，`git diff --check` 通过。
- 完整 `stable`：首次 reviewer 前运行到 `1111/1738` 时暴露上述旧 2026 fixture；按本轮要求修正并验证该单测后未重新启动超长全量回归。
