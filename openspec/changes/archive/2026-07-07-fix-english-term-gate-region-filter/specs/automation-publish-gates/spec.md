## ADDED Requirements

### Requirement: 英文核心术语硬门禁必须排除高歧义误命中
系统 SHALL 在生成 `core_term_missing` blocker 前评估英文术语命中的可信度。英文普通词、短词、高频误挡词或缺少强赛马上下文的术语命中 MUST NOT 默认生成 blocker；系统 SHALL 将其降级为 warning 或 info，并记录降级原因。

#### Scenario: 普通英文词不触发硬门禁
- **WHEN** 英文文章命中被配置为高歧义的正式术语 `CLASS`
- **AND** 该命中缺少强赛马实体上下文
- **THEN** 系统 SHALL NOT 生成 `core_term_missing` blocker
- **AND** 系统 SHALL 记录包含术语、术语 ID、命中位置和降级原因的 warning 或 info

#### Scenario: 可信核心赛事缺失仍然阻断
- **WHEN** 英文文章在标题或首段命中同地区高可信赛事术语
- **AND** 发布稿缺少该赛事的中文译名、原文或可接受别名
- **THEN** 系统 SHALL 生成 `core_term_missing` blocker
- **AND** 文章 SHALL NOT 被标记为 `publish_ready`

#### Scenario: 高价值来源不绕过可信核心术语 blocker
- **WHEN** 英文文章来自高价值来源或榜单来源
- **AND** 该文章存在可信核心术语缺失 blocker
- **THEN** 系统 SHALL 保留 blocker 阻断结果
- **AND** 不得仅因来源高价值将文章标记为可自动发布

### Requirement: 术语误挡修复后必须支持受控重处理
系统 SHALL 提供受控入口重新处理近期因术语 blocker 转入人工审核的文章。重处理 MUST 支持 dry-run、地区、来源和时间范围限制；提交模式不得直接公开文章，只能重新运行评分和发布校验，使通过门禁的文章重新进入发布候选。

#### Scenario: dry-run 重处理不修改文章
- **WHEN** 运维人员以 dry-run 模式重处理最近 72 小时美国 `manual_review_required` 文章
- **THEN** 系统 SHALL 输出预计变为 `publish_ready`、仍被 blocker 阻断和忽略的文章数量
- **AND** 系统 SHALL NOT 修改任何 `NewsArticle` 状态

#### Scenario: 提交重处理让通过文章重新进入窗口
- **WHEN** 运维人员提交重处理一篇此前仅因高歧义术语误挡的文章
- **THEN** 系统 SHALL 重新运行发布校验
- **AND** 若该文章不存在 blocker，系统 SHALL 将其标记为可自动发布候选
- **AND** 系统 SHALL 记录可被发布窗口回看的复审时间或等价信号

#### Scenario: 重处理不绕过人工终态
- **WHEN** 待重处理文章已被人工拒绝、撤回或标记为重复内容
- **THEN** 系统 SHALL 跳过该文章
- **AND** 输出跳过原因

### Requirement: 发布窗口必须保留术语门禁诊断
系统 SHALL 在发布窗口候选决策或生产审计中保留术语门禁诊断，使运营能够区分真正 blocker、高歧义词降级和无候选。

#### Scenario: 文章因可信术语缺失被阻断
- **WHEN** 某候选文章因可信 `core_term_missing` blocker 未入选发布窗口
- **THEN** 窗口候选决策或审计输出 SHALL 包含 blocker 术语、术语类型、术语地区、文章地区和阻断原因

#### Scenario: 文章命中高歧义词但通过门禁
- **WHEN** 某候选文章命中高歧义术语且该命中被降级
- **THEN** 系统 SHALL 在文章门禁 issues 或审计输出中记录降级原因
- **AND** 不得把该降级结果计入硬门禁阻断数
