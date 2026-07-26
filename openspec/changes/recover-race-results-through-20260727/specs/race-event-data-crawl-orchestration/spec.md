## ADDED Requirements

### Requirement: 赛果追补必须支持结果专用编排
编排工具 SHALL 在 `race_result_recovery` purpose 下接受冻结 event ID 和仅含 `results` 的模块范围，不得强制同时抓取 `runners` 或 `history_winners`。

#### Scenario: adapter 同时返回多个模块
- **WHEN** 结果追补 adapter 返回 runners、results 或 history_winners
- **THEN** aggregate 必须只保留批准的 results 模块，且 coverage 不得因未请求模块缺失而失败

#### Scenario: 普通赛事详情 run
- **WHEN** purpose 不是 `race_result_recovery`
- **THEN** 现有三模块完整性与历史深度规则必须保持不变

### Requirement: 结果专用输入必须来自已批准应到清单
系统 MUST 从绑定 SHA 的 inventory 逐地区生成 adapter 输入，并拒绝范围缩减、扩张、重复 event 或审批后字段漂移。

#### Scenario: 某地区候选为空
- **WHEN** inventory 该地区有应到事件但 adapter 没有产生对应结果候选
- **THEN** coverage 必须产生逐 event blocker，不得把该地区视为完成

#### Scenario: 本批精确来源全集
- **WHEN** 生成 `2026-07-08..2026-07-27` recovery adapter 输入
- **THEN** event ID 集合必须与 `source_research_20260727.md` 的日本 6、英国 11、法国 4、美国 19 场精确相等，event `924` 和 9 条重复产品行不得混入 40 场 candidate 分母

### Requirement: 来源确认层级必须贯穿结果恢复
编排产物 MUST 为每条候选标明 source authority、candidate/official 层级、route contract 和是否满足确认条件。

#### Scenario: TRA 返回非空结果
- **WHEN** TRA 候选通过结构与身份校验
- **THEN** 系统可以标记为 provisional candidate，但不得仅据此令结果 confirmed

#### Scenario: candidate route 没有自动化许可
- **WHEN** source registry/runner plan 没有明确允许该 host/path 的网络自动化
- **THEN** 编排必须在 transport 前 blocker；官方人工浏览权限不得被解释为自动抓取权限
