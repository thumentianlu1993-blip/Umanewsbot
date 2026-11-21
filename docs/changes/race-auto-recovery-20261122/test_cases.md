# 范围验证

- 已有RED记录：JRA取消马号阻断结果链接、英国Steeple Chase目标及跨日发现、旧单源覆盖v2、严格恢复。原始测试日志存专用runtime目录，不把线上读取当自动测试。
- 首轮160项离线PostgreSQL回归通过；review补测真实旧rotate全部写入后的恢复、拒绝恢复的持久due、双向赛名匹配，三项均取得预期RED。
- 完整旧轮转测试仅临时将fixture authority_version设为1来绕过新增入口guard，实际执行rotate的全套代次、字段和checkpoint写入后恢复v2标识；不手写假设的轮转字段。
- JRA完整/部分名单、链接身份、结果修订及幂等沿原模块回归；退赛结果保持合法名次，且包含退赛马。
- 自动恢复E2E：自然discover→selector提交合法claim→Celery worker入口→正式revision/publication→公开可见→原sent incident resolved；重复旧claim无抓取及二次发布。
- 拒绝路径：manifest哈希不符、未证实代次、人工暂停、活跃claim、未知checkpoint合同、过期binding；事务不留下局部写入或成功审计。
- 影响范围包含race_priority_lifecycle、全部多源登记与旧登记、UK采集工作流、测试选测工具；固定树断网Linux/隔离PostgreSQL结果由CI收据绑定，不使用全量测试。

最终数量与独立审核结论在交付包/PR列明；本文件不把阶段通过称为生产验收。
