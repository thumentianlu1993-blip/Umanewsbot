# 历史迁移测试隔离与现行合同对齐

## 根因与范围

PR #188 `61afbf59` 的 [Linux/PG16 CI](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/34329843286)
有 28 条不可逆迁移准备错误，涉及 5 个模块、16 个测试。测试直接回退当前 0078 数据库，部分 teardown
还只恢复到旧 leaf。第一轮 PR #191 `721428a2` 改为测试专属 PostgreSQL schema／SQLite 内存库，真实执行
迁移；保留已发布迁移及原 test_* 函数体。正常或异常退出后恢复原连接，只删除本次创建的隔离环境。

第一轮 [CI 34337262093](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/34337262093)
实测 4,945 项、37 failures、229 errors、20 skipped，264 个唯一失败 ID；相对生产 `69955960` 消除 10 个，
没有新增。28 条准备错误全部消失，但 6 个测试暴露后续断言失败；另一个同模块审计夹具原错误仍在。
新增两项隔离／异常清理回归无失败或跳过，45 项发布专项及 Linux 正式前后指纹通过。

## 七项后续修正

本次只改两个测试模块及本文，不改变应用、已发布迁移、业务规则或恢复策略。

| 原问题 | 修正及保留的验证 |
| --- | --- |
| P0 迁移用仓库 graph leaf 判断数据库是否已到 0052，仓库现已到 0078 | 检查实际已应用的 stable 节点恰等于 0052 的全部前驱，且到 0052 计划为空；保留原回填、索引、唯一性、回退与重放断言 |
| 审计测试仅抹去 0068–0075 recorder，遗留 0076–0078，不能满足精确修复态 | 在私有数据库真实迁移到 0067+0070，再生成 receipt；保留输出守恒、repeatable-read/read-only、无 INSERT/UPDATE/DELETE 检查，并核对 recorder 未变 |
| 旧初装测试期望 0067、0068+0070、0069+0070、0075 都可由当前候选推进 | 保留四个真实 schema/catalog 检查，精确区分旧 0077 计划和当前多出的 0078，验证拒绝这些历史状态 |
| 旧 0073→0075 普通发布成功流程 | 当前合同只允许 0077→0078／0078 同版本；改为真实 handoff 命令拒绝 0073，断言具体状态错误、零写入、schema/recorder/文件不变 |
| 旧 pre-0070 初装空 receipt 成功流程 | 验证当前命令拒绝该 origin，不创建 handoff、marker 或 receipt 表；空 receipt 不能形成绕过 |
| 旧 0070 修复完成流程 | 当前候选不能接管旧世代恢复；真实创建旧 marker，验证 resume 在 preflight 拒绝，marker 原字节、零 receipt、schema/recorder 均保留 |
| 初装 artifact 配修复 marker 的旧晚期错误消息 | 当前 verifier 更早拒绝不受准入合同支持的 artifact；同时验证具体 `release_0078_recovery_binding` 错误、命令拒绝及 marker/文件/recorder 不变，不只改异常匹配文字 |

这些调整基于 `historical_calendar_release_b_schema.ALLOWED_FORWARD_STATES`、
`release_0078_recovery.validate_admission_state` 及当前 handoff 命令的实际合同，不扩大允许状态。
四个旧成功测试重命名为当前拒绝合同测试，CI 需按映射核验替代用例确实执行；不能仅因旧 ID 消失算修复。
有效的 0078 升级、锁超时原子性、备份恢复以及 create→verify→ensure→migrate→complete 正向流程，继续由
`Release0078PostgresTests` 的真实 PostgreSQL 专项覆盖，尤其是
`test_real_v5_handoff_commands_migrate_and_archive_exact_0078_receipt`；这些用例和断言未修改。

## 验证边界

第一轮 Windows/SQLite 两项隔离回归及三项原历史迁移回归共 5 项通过（90.199 秒），原 reviewer 审核通过。
本次 PostgreSQL 专属测试仍需固定新候选 CI，不能用本机跳过或第一轮通过代替。独立复审及结果记录在
`runtime/fix-migration-test-contracts/`；第一轮证据保留在 `runtime/fix-historical-migration-test-isolation/`。
不增加 expectedFailure、skip 或替换生产校验器；失败和后续暴露问题完整记录。

人工交付边界统一见根 `AGENTS.md`。没有生产操作。