# 验证记录

- 新覆盖报告模块缺失时取得 RED；独立复审的“confirmed/unconfirmed 混合行误闭环”和“policy incident 重开沿用发送时间”均补测试取得 RED，再修复。
- 七场恢复模块缺失时取得 RED；六项恢复测试验证 dry-run 无写入、退役/CAS/结果写入、重复执行、缺行/摘要/baseline 漂移、活跃 claim/人工暂停、writer 失败全批回滚及恢复后资料漂移。
- 38 项覆盖/告警/多来源登记回归通过；新增真实 PostgreSQL 并发 census 锁与 SMTP lease 测试通过。
- 扩展到原受审结果 writer 和旧 stalled-event repair 后共 88 项，出现两项旧 repair 测试失败，需对照基线记录，不能表述为全量全绿。
- 已对七场真实本地 HTML 重新解析、比对完整参赛名单及结果，52 行通过；此步骤为来源验收，不混称自动测试。
- 生产 dry-run、最终回归、独立 review、部署与公网证据在 rollout.md 收尾。
