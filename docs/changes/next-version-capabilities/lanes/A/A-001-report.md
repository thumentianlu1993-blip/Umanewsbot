# A-001 / F01 阶段交付

阶段：方案可审。时间：2026-10-03，Asia/Shanghai。DDL：10/04 18:00；当前提前交审，定值/审核仍须在 DDL 前闭合。

已完成：代码定位、[F01 方案](F01-plan.md)、[四组输入输出及反例](F01-contract-examples.json)、
兼容与迁移索引草图、参数决策来源区分、A/B/C 消费边界；另附 [F03/H01 只读准备](F03-H01-readonly-preparation.md)。
部分完成：共享类型为可实现草案，尚未进入 Python/ORM；参数键与未知值确定，但数值/社区清单未定版。
仍待进行：协调者定值、R 独立方案审核、原 reviewer finding 修复复审、固定最终合同 SHA 后派发实施。
F01 未报告开发完成，F03/H01 未报告完成。

工作树 `/Users/mentianlu/.codex/worktrees/5482/umanews`，分支 `codex/next-version-race-data-20261003`。
base `907f8de699b31a6fcc80acc78e9ba070aadc4f28`；继承规划 `63b5781e`（源 `d0cec076019f35b6f7db56b09ebee291e57fd9f9`）。
本阶段提交 SHA 以 Git 与给协调者的消息为准，避免提交自身 SHA 循环。改动仅 `lanes/A/`，无应用代码、迁移、配置或生产改变。
没有 push/PR/合并/部署；共享主线由协调者按根 AGENTS.md 组织。

验证：[F01-validation.json](F01-validation.json)：四组 JSON/哈希、引用/动作、链接、源码锚点通过；
`check_workflow_contract.py` PASS；`test_workflow_contract.py` 4/4 PASS；`git diff --check` PASS。
这是文档验证，不是新行为 RED/GREEN、Linux 交付测试或自然生产验收。独立 review 尚无证据。

下游：A 使用身份/分母和 source capability 合同；B 使用 evidence/input_version/budget 候选合同；
C 使用 public summary/异常/protection/CAS 合同。方案状态期间可准备 fixture，不能声称冻结接口可实施。
模型供应商/新闻代码归 B，公开/后台页面归 C；A 只汇总 schema DAG，不实现其他线业务。

待协调选项与推荐：

- 推荐采纳文档列出的 P0∪G1/Jpn1/港本土G1 重点候选规则，但需核验人工重点映射后输出实际名单；不猜赛名。
- 推荐三年/90天/未来30天及阶段时限作为显式配置建议，逐项记录协调决定，不伪称老板原数字。
- 社区认可清单现无已核验证据：推荐先隔离候选、指定 B H04/H05 与协调者核定，不默许全网。
- 真实预算未明：推荐金额 null 时阻止真实付费调用、B 继续 mock 开发；F06 10/06 确认套餐/额度及吞吐。
- 请协调者安排 R 审核本文方案与四组样例；重点看第三方确认与旧公开权限兼容、依赖哈希闭集、锁与未知值。

这些未决项可能影响 F01 最终定版及 F03/M01 下游解锁；本轮无已知新增超过一个工作日切片。
