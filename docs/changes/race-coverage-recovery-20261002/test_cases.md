# 验证记录

- 新覆盖报告模块缺失时取得 RED；独立复审的“confirmed/unconfirmed 混合行误闭环”和“policy incident 重开沿用发送时间”均补测试取得 RED，再修复。
- 七场恢复模块缺失时取得 RED；六项恢复测试验证 dry-run 无写入、退役/CAS/结果写入、重复执行、缺行/摘要/baseline 漂移、活跃 claim/人工暂停、writer 失败全批回滚及恢复后资料漂移。
- 38 项覆盖/告警/多来源登记回归通过；新增真实 PostgreSQL 并发 census 锁与 SMTP lease 测试通过。
- 扩展到原受审结果 writer 和旧 stalled-event repair 后共 88 项，出现两项旧 repair 测试失败，需对照基线记录，不能表述为全量全绿。
- 已对七场真实本地 HTML 重新解析、比对完整参赛名单及结果，52 行通过；此步骤为来源验收，不混称自动测试。
- 生产 dry-run、最终回归、独立 review、部署与公网证据在 rollout.md 收尾。

## 最终本地回归（待生产验收）

- 85 项相关 PostgreSQL 回归全部通过，包括 2 项真实并发、7 项恢复与覆盖门禁回归。18 项 0079 发布合同全部通过。后者首次因 macOS `/var` 临时目录是 symlink 被保护函数拒绝，改用真实 `/private/tmp` 后通过，未修改发布合同代码。
- 旧 repair 的两个失败已在只含 `070eaeda` 原代码的隔离目录重现：`test_apply_repairs_stalled_event`（standing_policy_expired）、`test_apply_rejects_entry_closed_since_dry_run`（immutable revision fixture）。不将其算作本批通过。
- 第二轮只读 review 的三项 P2 均补有效 RED 后修复：旧 SLO 关闭新告警、零行/非完赛被计 confirmed、幂等漏检 reported position 和 owner generation。最终复审另记。

## 首发后的队列隔离补正

- 隔离 memory broker 放入 100 条合成新闻任务，再用实际 Beat options 或实际 task routes 发布监控。仅消费 race_sync_v2；原实现两例均 RED（监控不可领取），修正后两例 GREEN，新闻队列仍保留 100 条。加载配置时同时关闭 writer/scheduler/discovery，验证覆盖 flag 独立生效；不访问生产数据库、Redis 或第三方。
- 隔离 PostgreSQL 的覆盖、恢复、告警、多来源登记、受审写入和 data-sync R0 合同共 144 项通过，Django check 无问题。最终云端对照与独立复审另记。
- 独立复审指出 Celery 环境变量可覆盖 broker 构造参数，且 python-dotenv 1.1.0 不识别 DOTENV_DISABLED。补两例无网络探针取得 RED，再将隔离覆盖整个配置加载/消息生命周期：清空环境、mock dotenv loader、固定内存传输并在队列操作前断言、禁止 socket connect、隔离 memory broker 全局状态，彻底移除 purge。四例通过；不连接或清理任何真实队列。
