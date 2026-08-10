# lifecycle enforce canary 锁定方案

本方案以 `spec.md`、`design.md`、`test_cases.md`、`tasks.md`、`rollout.md` 为完整合同。

锁定决策：

1. 只允许 manifest 绑定的两场 canary；生产授权必须精确为 event 186/187。
2. 先 false/off，再原子提升 control，再受审切 true/enforce；不从 true/shadow 原地热切。
3. 全局 enforce 不是充分条件；独立 env/settings SHA+IDs、control canary 证据与两场共享 active
   activation ID 必须一致才能公开写入；promotion 初始状态只能是 inactive。
4. 其他 control 保持 shadow；scanner、状态机和 transition 模型全部复用。
5. 无 migration；promotion 由 shared deployment lock 和 PostgreSQL advisory xact lock 串行；模式提升
   审计写入冻结 artifact、control manifest_data + OperationLog，状态推进继续写 applied transition。
6. apply freshness 为 24h；runtime validity 覆盖最晚 T+30 后 24h，不要求 event187 前重做 manifest。
7. false/off 是不依赖 artifact 的一级止损；不自动反向赛事状态。
8. 测试先行、独立方案 review、独立代码 review；生产启用另等精确 G3。
9. host manifest 只通过有界 stdin 进入容器；成功顺序不含额外手工 scanner，由 Beat 首个 tick 验收。
