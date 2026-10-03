# A-006 测试影响映射提案（交root，未应用共享文件）

建议新增domain `horse_target_inventory`，tests为 `stable.test_horse_target_inventory`、`scripts.tests.test_h01_readonly_count`，两个label profile均明确 `python`（纯unittest、fake连接，不启动PG）。

| exact path | domain |
|---|---|
| server/stable/services/horse_target_inventory.py | horse_target_inventory |
| server/stable/test_horse_target_inventory.py | horse_target_inventory |
| scripts/h01_readonly_count.py | horse_target_inventory |
| scripts/tests/test_h01_readonly_count.py | horse_target_inventory |

本线新增/更新文档均MD，沿现有精确文档目录规则；不扩大JSON/HTML免测路径，不改runner、skip、bootstrap或full规则。root集成proposal后原R限定复核，再以真实PR基准生成计划。手动28项Linux专项只作为此固定tree的开发证据，不替代正式收据。源码新路径未映射时fail closed，不伪造空选集绕过。
