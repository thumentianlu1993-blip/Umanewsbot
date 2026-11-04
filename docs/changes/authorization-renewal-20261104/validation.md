# 验证与交付边界

- 新增长期有效期用例先 RED：生命周期不接受显式截止参数、TRA 不接受 v3；实现后相关回归通过。
- 已完赛成员续期先 RED（缺少续期入口），再通过真实生产单成员只读快照的隔离演练：dry-run、promotion、inactive verify、activation、active verify 全部成功，赛事行保持不变。该演练 `production_shape=false`，不代表生产已续期。
- 独立只读 review 找到 P1：runner 将v3退回单页；新增目标仅在第二页且证据第40天的真实runner用例，RED复现，修复后89项通过。原reviewer复审关闭P1，无新增actionable finding。复审前后指纹一致。
- 固定生产候选 `ab5775f62619ec196aed7bd7f87f65236b53dfa8`：150项 SQLite 回归通过；82项 PostgreSQL16 隔离回归通过，零失败/错误/跳过，容器 network=none、非root、生产服务不可访问。
- PostgreSQL测试镜像：`sha256:5fa59696f087c4ba2fdc0fde4e6c95d484e660334332a0256ba739a911766d42`。这是离线测试运行时，不能当作生产镜像。
- 主线完整CI与候选外交付核验以本PR实时checks及外部收据为准；本文件不预写尚未完成的CI结论。合并/生产执行状态单列于发布记录。

本次无模型、迁移、调用预算和抓取范围变化。TRA 两份文件逐字一致，14条standing路线范围保持相同。审批绑定见 rollout.md；完整manifest和测试日志保留在本任务专用runtime。
