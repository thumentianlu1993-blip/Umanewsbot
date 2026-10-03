# A007 PG测试映射提案（未应用）

路径：server/stable/test_h01_count_postgres.py；label：stable.test_h01_count_postgres；domain：horse_target_inventory；profile：复用已有django真实PG profile。原两个planner/reader标签保持python，不将PG测试塞入dummy/python。root统一维护catalog/path规则及选择收据，本线不改共享文件。

5个method与mutation/隔离/observer/预算见A-006-PG-validation-preparation.md A007节。默认collect/run实际执行；非PG或非隔离test DB失败，无opt-in env/manifest，不新增skip allowlist。当前path为授权候选，源码尚未创建，不虚报collected IDs或PG通过。等待原R方案审核与B后排程，尚未启动容器。
