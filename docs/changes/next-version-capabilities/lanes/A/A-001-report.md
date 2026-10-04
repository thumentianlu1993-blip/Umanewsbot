# A-001 / F01 阶段交付

阶段：F01-M-01 已修订，待原 R 限定复审。时间：2026-10-03，Asia/Shanghai。DDL：10/04 18:00；当前提前交审，定值/审核仍须在 DDL 前闭合。

已完成：代码定位、[F01 方案](F01-plan.md)、[四组输入输出及反例](F01-contract-examples.json)、
兼容与迁移索引草图、参数决策来源区分、A/B/C 消费边界；另附 [F03/H01 只读准备](F03-H01-readonly-preparation.md)。
部分完成：共享类型为可实现草案，尚未进入应用 Python/ORM；首版默认参数已由协调者定值，社区清单仍pending、真实金额null。
仍待进行：原 R 对修订SHA限定复审、固定最终合同 SHA 后由协调者派发实施。
F01 未报告开发完成，F03/H01 未报告完成。

工作树 `/Users/mentianlu/.codex/worktrees/5482/umanews`，分支 `codex/next-version-race-data-20261003`。
base `907f8de699b31a6fcc80acc78e9ba070aadc4f28`；继承规划 `63b5781e`（源 `d0cec076019f35b6f7db56b09ebee291e57fd9f9`）。
本阶段提交 SHA 以 Git 与给协调者的消息为准，避免提交自身 SHA 循环。改动仅 `lanes/A/`，无应用代码、迁移、配置或生产改变。
没有 push/PR/合并/部署；共享主线由协调者按根 AGENTS.md 组织。

验证：[F01-validation.json](F01-validation.json)：四组 JSON/哈希、引用/动作、链接、源码锚点通过；
`check_workflow_contract.py` PASS；`test_workflow_contract.py` 4/4 PASS；`git diff --check` PASS。
这是文档验证，不是新行为 RED/GREEN、Linux 交付测试或自然生产验收。首审 R 结论 REVISE：无P0/P1，必要medium F01-M-01；已修正样例source/scope/保护摘要与所有受影响hash，原R复审尚待返回。

下游：A 使用身份/分母和 source capability 合同；B 使用 evidence/input_version/budget 候选合同；
C 使用 public summary/异常/protection/CAS 合同。方案状态期间可准备 fixture，不能声称冻结接口可实施。
模型供应商/新闻代码归 B，公开/后台页面归 C；A 只汇总 schema DAG，不实现其他线业务。

本轮返修与参数记录：

- F01-M-01：输入/输出source三元作用域一致，scope排序；loader派生保护摘要、wire缺失/篡改拒绝；明确所有必需/可空/派生成员。
- 新增离线文档校验器 `validate_f01_contract.py`：4个正例、5个非法输入/输出拒绝、4个无序集合重排摘要稳定、1个名单业务顺序变更摘要变化。不是业务共享类型或writer，不用这些检查冒充行为RED/GREEN。
- 首版可配置默认值按协调者本轮决定记录：三年滚动、90天新闻、未来30天优先，明确重点集合/阶段与前瞻期限、60次读取/1200秒/3轮、最低300场/100篇/20场。不冒称老板逐项确认。
- 社区pending由B整理既有认可依据/候选交协调者；金额null不执行真实付费，F06在10/06核额度。共享字段/mock可继续准备。
- 原R审稿报告是只读来源 `/Users/mentianlu/.codex/worktrees/3ab1/umanews/docs/changes/next-version-capabilities/lanes/R/A-001-F01-plan-review.md`，复审仍由协调者送同一R上下文。

用户追加资源约束已实时核验采纳：每周剩余<=1%立即保存最小断点并暂停；<=3%每批次检查；额度未知停止新增耗时工作；不使用积分/重置券继续。当前无子代理或模型CLI，后续每轮/长任务前及持续每5分钟检查。
本轮无新增产品范围、writer、应用测试/迁移、生产查询或实网调用。F03/H01仍只是准备材料。
