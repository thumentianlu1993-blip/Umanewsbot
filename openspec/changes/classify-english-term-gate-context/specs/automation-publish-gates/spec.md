## ADDED Requirements

### Requirement: 英文术语门禁必须按上下文区分普通词和专有名词
系统 SHALL 在英文来源文章的术语保留校验中，根据命中上下文判断未保留的英文术语是普通英文词还是真实赛马专有名词。高置信普通英文词不得生成自动发布 blocker；真实专有名词仍 MUST 按核心术语缺失规则阻断；无法确定的命中 MUST 保守进入人工处理或保留 blocker。

#### Scenario: 普通英文词不阻断自动发布
- **WHEN** 英文文章命中正式术语 `Contact`、`Number`、`Live`、`Were` 或同类普通英文词
- **AND** 该命中在上下文中被高置信判定为普通词
- **AND** 文章不存在其他 blocker
- **THEN** 系统 SHALL 不生成 `core_term_missing` blocker
- **AND** 系统 SHALL 记录普通词降级 warning 或 info

#### Scenario: 真实赛事名继续阻断
- **WHEN** 英文文章命中 `Belmont Stakes`、`Kentucky Derby`、`Prix Ganay` 或同类真实赛事名
- **AND** 中文发布稿未保留正式中文译名或中文 alias
- **THEN** 系统 MUST 继续生成 `core_term_missing` blocker
- **AND** 系统 MUST 不得因英文普通词规则放行该文章

#### Scenario: 可双关马名低置信时不自动放行
- **WHEN** 英文文章命中 `Tuesday`、`GOOD JOB`、`Fast Track` 或同类既可能是普通词又可能是马名的词
- **AND** 系统无法高置信判断该命中是普通词
- **THEN** 系统 MUST 保持 blocker 或转入人工审核
- **AND** 系统 MUST 在 issue payload 中记录不确定原因

#### Scenario: 地区过滤优先于语义判定
- **WHEN** 英文文章命中其他地区的正式术语
- **THEN** 系统 SHALL 继续按地区过滤规则将该术语排除或降级
- **AND** 系统 SHALL NOT 为该跨地区术语调用普通词/专有名词语义判定

#### Scenario: 分类结果必须可审计
- **WHEN** 系统因英文术语语义判定降级或保留一个门禁 issue
- **THEN** issue payload 或 validation details MUST 包含术语 ID、原始词、命中文本、命中上下文、分类结果、置信度和原因
- **AND** 后台或审计命令 MUST 能读取这些字段解释文章为何放行或继续阻断

#### Scenario: 普通词种子必须可追溯
- **WHEN** 系统使用普通英文词集合辅助降级门禁
- **THEN** 该集合 MUST 来自仓库内可 review 的配置、常量或审核 artifact
- **AND** 系统 MUST NOT 依赖聊天记录或生产临时状态作为唯一判断来源

### Requirement: 旧英文核心术语 blocker 必须支持优化版完整重校验
系统 SHALL 提供受控重校验能力，对指定地区、时间窗和旧 `core_term_missing` 候选执行完整自动发布门禁 dry-run。该能力 MUST 避免无界扫描历史积压，并 MUST 输出每篇文章当前是否通过、仍被哪些 blocker 阻断以及哪些英文术语被普通词语义判定降级。

#### Scenario: dry-run 不写生产数据
- **WHEN** 运维人员执行旧英文核心术语 blocker 重校验 dry-run
- **THEN** 系统 MUST 输出候选文章 ID、通过列表、仍阻断列表、blocker、warning 和英文术语分类明细
- **AND** 系统 MUST 不修改 `NewsArticle` 状态、门禁字段、发布时间或发布窗口记录

#### Scenario: 重校验候选集有界
- **WHEN** 运维人员指定地区、时间窗、来源或数量限制执行重校验
- **THEN** 系统 MUST 只扫描满足过滤条件且当前存在 `core_term_missing` blocker 的未发布候选
- **AND** 系统 MUST 不默认遍历全部历史人工审核文章

#### Scenario: commit 只恢复完整通过文章
- **WHEN** 运维人员对已审核的重校验结果执行 commit
- **THEN** 系统 MUST 仅对完整门禁通过的文章应用校验结果并恢复到可发布候选
- **AND** 系统 MUST 不直接公开发布文章
- **AND** 仍有 blocker 的文章 MUST 保持人工审核或阻断状态

#### Scenario: 重校验结果可对照本批审计投影
- **WHEN** 运维人员对 7 月 1 日以来香港、英国、美国、法国旧 `core_term_missing` 候选执行完整 dry-run
- **THEN** 系统 MUST 输出按地区聚合的旧 blocker 清除数、普通词降级数和仍被真实专名阻断数
- **AND** 系统 MUST 保留文章级明细，便于对照既有人工审计投影和抽查误放行风险
