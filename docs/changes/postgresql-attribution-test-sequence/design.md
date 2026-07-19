# PostgreSQL 归属测试序列修复设计

## 现状分析

`AttributionRunLedgerTests` 是事务测试类，类内创建的文章和 run 仅通过各自实际生成的
`id` 做关联或结果比较，没有任何 `id == 1` 等固定主键断言。因此它需要
`TransactionTestCase` 的事务/清库行为，但不需要 `reset_sequences=True`。

迁移种子数据与 Django 的 PostgreSQL 序列重置组合会产生以下冲突：

1. 测试库执行迁移，迁移通过普通 `create` 建立的种子行已占用
   `stable_termentry` 的低位 ID。
2. `reset_sequences=True` 在测试前无视表内现存最大 ID，把
   `stable_termentry_id_seq` 重置为 `1`。
3. 测试调用 `TermEntry.objects.create()`，PostgreSQL 分配 `id=1`。
4. 现有种子行占用 `id=1`，触发 `UniqueViolation`。

## 方案

仅移除 `AttributionRunLedgerTests.reset_sequences = True`。

Django 仍按 `TransactionTestCase` 语义隔离测试并 flush 测试写入；PostgreSQL 序列保留迁移
执行后的正确位置，测试只依赖 ID 唯一性和对象间关系，不依赖确定的起始值。

## 数据与迁移

- 无模型变化。
- 无迁移变化。
- 无生产数据写入。
- 无运行时数据流变化。

## 回滚

恢复该类的 `reset_sequences=True` 即可回滚代码变更，但 PostgreSQL 测试主键冲突会重新出现。

## 风险

- 风险限于测试之间若错误依赖固定 ID；整类和相关回归测试用于发现此类隐式依赖。
- SQLite 不会暴露同样的迁移种子/序列行为，因此必须保留 PostgreSQL 验证作为主要证据。
