# 方案检查记录

2026-11-01。审核方式：作者按仓库plan-eng-review清单做只读自检后修正文档；**不构成独立review批准**。

## 自检finding与处理

[medium] 不能把协议错误导致的转人工当作识别到原文歧义。
- 证据：evaluation.md原“正确转人工率”仅检查gold期望与最终review状态。
- 问题：模型返回非法JSON也可能恰好把应送审文章送审，不能由此声称语义判断正确。
- 影响：高协议失败率会虚增不确定识别能力。
- 要求与落实：拆为安全拦截率和有依据的不确定识别率；只有可核对的原文歧义证据才计后者，缺可观察证据记N/A；A07加入反例。修正后复核两指标与主通过率独立，无剩余自检阻断项。

## 检查输入与覆盖

输入包括spec、annotation、dataset、evaluation、design、test_cases、tasks、rollout及examples.json；对照现有news_entity_units、news_content、news_evaluation契约与current_state。覆盖范围、类型/边界、人工gold、数据隔离、分组泄漏、分母/退化/成本、故障与防重、旧75/25兼容、无生产改动及恢复交接。

7组合成标注示例的9个跨度（含允许变体）、JSON解析、本地文档链接和diff空白检查通过。合成示例未运行模型，不能证明模型质量或真实标注准确性。

## 独立审查未完成

已尝试只读`codex review --uncommitted`，会话`01a192fc-e8e1-73b0-9adb-747ae98e4181`持续`workspace routing discovery failed`，未生成审查结论；确认进程属于本次任务后停止重复连接。尝试前后工作区指纹一致，日志保存在`/Users/mentianlu/.codex/runtime/p01-entity-benchmark-20261101/`。之后只进行了上述自检修正与本记录写入，不冒称这些内容获得独立批准。

未验证的外部条件：真实缓存数量/许可、人工标注与锁定集保管资源、来源/时间分布、实际API配置及预算；均已列为后续执行准备项。设计可供用户评阅，独立方案审查仍待恢复；不得把下面的自检结论当作实施或生产验收。

以下VERDICT仅指作者自检，没有独立审查含义。

VERDICT: APPROVED
