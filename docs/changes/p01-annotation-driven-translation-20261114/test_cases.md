# 测试案例

- RED：旧实体类型表拒绝race_related/racing_honor/auction/umamusume；新v3应接受，legacy/v2继续拒绝。
- 初轮含decisions拒绝；repair需决策；新类别在修复候选、occurrences及发布重放中一致；v2/v3混用拒绝。
- 标题、正文重复名、emoji码点、相邻冠名括号、跨块片段分别定位；不将日期/地点吞进赛事名。
- 新类别经保护/翻译/恢复，已有确认译名一致、无译名原文保留；非实体可正常翻译；丢失、重复、换块、未知token、矛盾译名拒绝。
- glossary必须和冻结实体一致；模型prompt/契约版本变动不能复用cache；完整v3流水线及发布重放验证。
- 评估器：漏标/误标/错类型/错边界/重复/重叠/无实体/无结果/超时/截断/变体最大匹配；失败分母、P/R N/A、基线退化、分片段与组统计。
- importer：120篇与哈希；未知类型/重复ID/伪造group/错误Unicode跨度失败；曝光与跨集合事件组显式记录，不能提升human gold状态。
- 事实评估：数字一致但人物/马匹对调、计划变已发生、引语归属错误、否定丢失、标题/摘要新增事实、遗漏引用；缺项/过期SHA/无目标证据/非人工或独立审阅状态不能自动当合格全文。
- 保留旧P01测试，运行影响计划与根workflow contract、diff检查；正式交付使用固定Git源码、隔离无网络Linux/PG测试证据。

- 容量129/256/257与v2边界；同sample错source/ref/variants SHA拒绝；不同manifest报告不可比较。
- 旧pending/stale切换新v3再用v2新rollout_revision，保留旧run与账证、拒绝旧claim结果投射；回滚时不使用原v2策略哈希。
