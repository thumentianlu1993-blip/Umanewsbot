# PostgreSQL 归属测试序列修复规格

## 背景

`AttributionRunLedgerTests` 使用 `TransactionTestCase.reset_sequences = True`。Django 在
PostgreSQL 测试库中无视表内现存最大 ID，把 `stable_termentry_id_seq` 重置到 `1`；迁移
此前通过普通 `create` 建立的种子行已经占用低位 ID，测试随后创建 `TermEntry` 时因此发生
主键冲突。

## 范围

- 让 `AttributionRunLedgerTests` 在包含迁移种子数据的 PostgreSQL 测试库中可靠运行。
- 保留该类现有事务测试语义、断言和业务覆盖。
- 记录真实 RED、GREEN 和相关 PostgreSQL 回归证据。

## 非目标

- 不修改业务运行时代码、模型、迁移或种子数据。
- 不改变生产数据库序列。
- 不修改归属算法、run ledger 或发布行为。
- 不引入通用序列修复框架。

## 验收标准

1. 精确失败用例在 PostgreSQL 16 上通过。
2. `AttributionRunLedgerTests` 整类在 PostgreSQL 16 上通过。
3. 相关多地区归属测试在 PostgreSQL 16 上通过。
4. SQLite 回归不受影响。
5. Django migration drift 检查保持无变化。

## 失败边界

- 若测试依赖固定主键，不能移除序列重置，须回到设计阶段。
- 若失败来自业务逻辑或迁移内容，不在本修复中扩大范围。
- 所有验证仅使用隔离临时数据库，禁止连接生产。
