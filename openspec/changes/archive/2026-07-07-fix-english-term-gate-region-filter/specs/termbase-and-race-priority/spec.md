## ADDED Requirements

### Requirement: 英文术语发布校验必须按地区过滤
系统 SHALL 在英文文章发布校验中按文章地区过滤正式术语。第一版默认校验范围 MUST 只包含文章同地区术语和全局通用术语。

#### Scenario: 香港术语不阻断英国文章
- **WHEN** 英国英文文章命中香港地区马名术语 `LINK`
- **THEN** 系统 SHALL NOT 因该术语生成 `core_term_missing`
- **AND** 系统 SHALL 在诊断 payload 中标记该术语因地区不匹配被排除

#### Scenario: 全局通用术语纳入各地区校验
- **WHEN** 英文文章命中 `racing_region=""` 的全局通用正式术语
- **THEN** 系统 SHALL 将该术语纳入发布校验
- **AND** 校验结果 SHALL 遵循同一可信度和高歧义判断规则

#### Scenario: 同地区可信术语纳入校验
- **WHEN** 美国英文文章命中美国地区高可信赛事术语
- **THEN** 系统 SHALL 将该术语纳入发布校验
- **AND** 发布稿缺失可接受保留形式时 MAY 生成 `core_term_missing` blocker

### Requirement: 英文术语库必须支持高歧义治理
系统 SHALL 支持对英文正式术语配置或派生高歧义治理结果。高歧义术语在翻译提示、术语命中、自动评分和发布校验中 MUST 保留可审计行为，不得无解释地触发或绕过发布门禁。

#### Scenario: 高频误挡词被标记为高歧义
- **WHEN** 术语治理规则将 `CLASS`、`CONTENT`、`AGENT` 或等价词标记为高歧义
- **THEN** 系统 SHALL 在发布校验中对这些术语应用降级或强上下文要求
- **AND** 诊断 payload SHALL 记录命中的治理规则

#### Scenario: 强上下文允许高歧义马名升级
- **WHEN** 高歧义英文马名出现在标题或首段
- **AND** 附近存在明确马名上下文、来源结构化字段或外部实体证据
- **THEN** 系统 MAY 将该命中视为可信实体
- **AND** 若发布稿缺失可接受保留形式，系统 MAY 生成 `core_term_missing` blocker

#### Scenario: 治理不影响日文术语校验
- **WHEN** 日文文章命中既有日文正式术语
- **THEN** 系统 SHALL 继续使用既有日文术语校验和普通词过滤规则
- **AND** 不得因英文高歧义词治理改变日文文章的自动发布门禁

### Requirement: 多地区术语审计必须输出误挡风险
系统 SHALL 在多地区术语运营检查或生产审计中输出英文术语误挡风险，包括高频 blocker、地区不匹配排除、降级 warning 和仍需人工治理的术语。

#### Scenario: 审计输出高频 blocker 术语
- **WHEN** 运维人员执行多地区新闻生产审计
- **THEN** 系统 SHALL 按地区输出近期 `core_term_missing` 的高频术语、计数和示例文章

#### Scenario: 审计输出降级术语
- **WHEN** 英文术语校验将高歧义命中降级为 warning 或 info
- **THEN** 审计输出 SHALL 能统计这些降级术语的计数
- **AND** 输出 SHALL 区分降级、地区排除和真实 blocker
