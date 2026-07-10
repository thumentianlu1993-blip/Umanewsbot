## ADDED Requirements
### Requirement: 批量赛事详情候选必须具备编排审计证据
系统 SHALL 要求面向历史回填或跨地区批量导入的赛事详情候选具备编排工具产出的审计证据，避免未审计候选覆盖公开赛事资料。

#### Scenario: 批量候选具备审计证据
- **WHEN** 运维人员准备批量导入 `runners`、`results` 或 `history_winners` 候选
- **THEN** 系统 SHALL 能够关联该批次的 plan、coverage audit、review artifact 和 dry-run 结果

#### Scenario: 缺少审计证据的批量 apply
- **WHEN** 批量候选缺少 coverage audit 或 dry-run 证据
- **THEN** 操作流程 MUST 不将该批次视为可 apply
- **AND** runbook MUST 要求补齐审计或退回候选生成阶段

#### Scenario: 单场修复保持可用
- **WHEN** 运维人员执行明确的单场人工修复 JSONL
- **THEN** 系统 MAY 继续使用现有 `import_race_event_detail_candidates` dry-run/apply 流程
- **AND** 运维记录 MUST 说明该操作是单场修复而非历史批量回填

### Requirement: 历史回填不得自动改变赛事可见性
系统 MUST 保持赛事结构化数据补充与 `RaceEvent` 可见性控制分离。编排工具不得因为抓取到新数据而自动公开草稿或隐藏赛事。

#### Scenario: 已公开赛事补充数据
- **WHEN** 已公开 `RaceEvent` 通过编排工具补充出走表、赛果或历届冠军
- **THEN** 公开赛事详情页 MAY 展示新增结构化数据
- **AND** 系统 MUST 不改变该赛事的可见性字段

#### Scenario: 草稿赛事补充数据
- **WHEN** 草稿或隐藏 `RaceEvent` 通过编排工具补充结构化数据
- **THEN** 系统 MUST 保持该赛事不公开
- **AND** 系统 MUST 不因数据完整而自动发布赛事页

#### Scenario: 新 series mapping 候选
- **WHEN** 历史回填发现新的年度赛事或新的 series mapping 候选
- **THEN** 系统 MUST 将其保留为 review/draft 状态
- **AND** 系统 MUST 不自动创建前台可见赛事页

### Requirement: 三模块完整性必须在赛事详情候选中可见
系统 SHALL 在赛事详情候选和后台复核材料中展示 `runners`、`results`、`history_winners` 的完整性状态，使运营人员能够识别历史回填缺口。

#### Scenario: 候选三模块完整
- **WHEN** 某赛事年份同时具备出走表、赛果和历届冠军候选
- **THEN** 后台或 review artifact SHALL 标记该赛事年份为三模块完整

#### Scenario: 候选模块缺失
- **WHEN** 某赛事年份缺少出走表、赛果或历届冠军任一模块
- **THEN** 后台或 review artifact MUST 展示缺失模块
- **AND** 系统 MUST 不把该赛事年份标记为完整历史回填
