# A-005 / H01 方案交接

已完成本轮方案落盘，未实施目标生成或执行生产查询。代码阅读基线815、消费受审F01业务0e；不宣称main已交付。A-004 v4与v5包均未修改，F03缺口保留。

交付：H01-plan.md、H01-test-matrix.md（18项具体断言）、H01-readonly-count-plan.md（19张固定预计public.stable表、111字段白名单、有界查询/脱敏/截断规则）。责任仅H01及本线文档，未改共享模型、writer、F01或他线。

近期以2023-10-03..2026-10-03含边界的当地赛日与实际出赛证据为核心；历史2020起一级全名单保留Jpn1和港本土G1、未建档/未解/缺来源；两个集合分开并保留交集归属。优先参数沿F01未来30天/近期新闻90天。最近参赛而非马龄；跨源verified强身份去重；current revision、legacy冲突与并发增量分别留证。cache/staging/profile/实际public不混称。

待冻结：JG1历史归属、地区赛季证据、优先元组、legacy/更正取舍、读取预算。真实生产schema/索引、许可/人数/耗时及完整输入仍unknown。root/R先审方案；F06有界预检最多24条SELECT/120秒/500聚合行/2MiB，无并发，不自动执行；超限或缺输入partial，不拿试点旧量/抽样充全分母。

静态检查：19模型/111字段本地AST核对通过；18矩阵ID唯一；workflow contract PASS，4合同自测通过；git diff --check通过。检查明细在私有runtime `/Users/mentianlu/.codex/runtime/a005-h01-plan/validation.json`。这些不是H01业务RED/GREEN、真实数量冻结或生产容量证明。暂无模型迁移、配置、网络、付费或生产数据动作。
