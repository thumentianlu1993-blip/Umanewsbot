# 赛事关联服务 PostgreSQL 行锁修复

## 范围与根因

`HistoricalRaceEventTarget.event` 和 `RaceEvent.race_series` 都允许为空。
原关联与撤销查询在 `select_related` 的外连接上执行未限定表的 `FOR UPDATE`，
PostgreSQL 会拒绝；首轮事务夹具修复让测试越过隔离级别阻塞后，继续暴露这个应用缺陷。
RED 证据见 [PR #188 首轮 CI](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/34326831655)
的固定候选 `17807a80`，其中 5 条 apply/rollback 测试停在该数据库错误。

修复只调整本服务的锁定查询：目标及非空系列仍一起锁定；赛事与可空系列分别锁定，
并复用已锁对象供身份校验。首次关联、已有关联和撤销均保留对应行锁，直到调用者事务结束。
不改变匹配规则、审批摘要、发布账本、回滚校验或数据库结构，不执行生产关联或历史回填。
本模块的测试改用 `TransactionTestCase`，与 PR #188 的同一夹具修复一致，使服务能管理真实事务。

## 验证

- 保留原 22 项关联、身份漂移、账本失败和撤销原子性测试。
- 新增 PostgreSQL 独立连接回归：首次及重复关联后，其他连接的 NOWAIT 请求必须无法取得
  目标、赛事、系列的锁；提交后须全部能取得。SQLite 明确跳过这一个数据库专属用例。
- 新增无系列的已关联赛事回归：仍按身份冲突拒绝，关联和操作日志没有额外写入。
- Windows/SQLite 快速运行共 24 项：14 通过，5 failures、4 errors、1 skipped；失败集中于
  manifest 文件校验或符号链接限制，不能作为 PostgreSQL 加锁修复通过的证据。
  本机输入与日志保留在 `runtime/fix-reconciliation-row-locks/`。
- 交付前必须核对固定候选的 Linux/PostgreSQL 16 结果、完整失败集合及独立只读审核；
  PR 记录实际候选和结果，不以本机部分通过代替验收。人工交付边界统一见根 `AGENTS.md`。
