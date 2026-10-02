# 验证记录

隔离环境：macOS / Python3.12.13 / Django5.2.1 / PostgreSQL16.15；专用55482端口、
合成用户bounded_ci，无生产配置、队列和外部HTTP。历史50项按21组全部复现，未运行stable全量。

业务 RED：组1实际PG varchar(32)溢出；组2五地区选取因 australia 缺3series拒绝；
组19公开页面缺中文译名/资料状态提示。最小修复后原用例通过。其他组为fixture/入口修复，
不把文件缺失、测试设置错误说成业务RED。

T3诊断：只把pipeline时钟固定到fixture NOW，原5项即通过；生产合同不改。
第10组9项替代测试实际调用正式工具，HTTP mock、预算/间隔/磁盘保护真实执行，全部通过。

相关回归固定为501项、4批（122/141/147/91），本地四批全部通过、零失败零跳过；Linux 固定 SHA 的同四批验证已通过。
有界入口12项自测覆盖选集上限、重复/错名/空集、50项映射、证据漏项/错SHA/跳过/失败拒绝。
不运行或宣称通过全量5682项。未入选的opt-in性能用例保持原状。

本地 0079 发布合同18项通过，Django check、makemigrations --check --dry-run通过（无迁移），
workflow contract检查及4项自测通过，YAML解析、git diff --check通过。
代码审核返修的生命周期失败传播、原始标签重复检查取得明确RED后修复。

固定提交 `ad50abdb` 的云端运行 36976989113 全部通过：49 项 0078 与 18 项 0079 合同，
12 项入口自测及有界完整性聚合均通过；Django check 无异常、无迁移漂移、测试前后指纹一致。
生产只读验收及边界见 rollout.md 与 production-validation.json。
