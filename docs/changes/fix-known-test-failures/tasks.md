# 实施顺序

- [x] (operations) 核验失败证据、当前分支及 CI，建立50项清单和21组方案。
- [x] (operations) 独立只读 agent 审核五份方案并在同一审核上下文完成修订。
- [x] (operations) 建立隔离 PG、有界 runner、基线分组失败证据。
- [x] (integration) T1/T2/T3/T5/T7 最小 RED → 修复 → 同组 GREEN 与相邻回归。
- [x] (application) T4/T6/T8/T9 最小 RED → fixture/模板修复 → 分组 GREEN。
- [x] (operations) T10/T11 CI 有界入口与配置合同修复、Linux 分组验证。
- [x] (operations) 清单完整性对账；同一代码 reviewer 独立只读审核及修复复审。
- [x] (operations) 固定 SHA 验证、commit/push/Draft PR，回写实际状态及精确发布包。
- [x] (operations) 按根 AGENTS.md 完成交付；发布后只读健康验证、恢复记录与 current_state 回写。
