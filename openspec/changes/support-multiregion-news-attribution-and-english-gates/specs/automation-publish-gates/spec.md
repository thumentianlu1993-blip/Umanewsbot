## ADDED Requirements

### Requirement: 英文门禁必须结合内容类别分层处理
系统 SHALL 在英文新闻自动发布门禁中结合内容类别、主地区、相关地区和术语语义分类结果决策 blocker、warning 和 info。普通英文词误挡 MUST 继续降级；可信核心专名缺失 MUST 继续保护；不同内容类别 MAY 使用不同自动发布和 QQ 资格策略。

#### Scenario: 赛果简报允许自动发布
- **WHEN** 英文文章被分类为 `result_brief`
- **AND** 文章通过正文、重复、URL、地区和可信核心术语门禁
- **THEN** 系统 SHALL 允许该文章进入自动发布候选

#### Scenario: 重大赛事赛前展望允许自动发布
- **WHEN** 英文文章被分类为 `preview`
- **AND** 文章关联 P0/P1 或等价重大赛事
- **AND** 文章不存在 blocker
- **THEN** 系统 SHALL 允许该文章进入自动发布候选

#### Scenario: 普通投注倾向 tips 不默认推高
- **WHEN** 英文文章被分类为 `tips`
- **AND** 文章主要包含选号、赔率、free bet 或投注营销表达
- **THEN** 系统 SHALL 允许站内发布策略将其降权或转人工
- **AND** 系统 SHALL NOT 仅因该文章评分高就认定其可进入 QQ 高价值推送

#### Scenario: 官方通知按类别保守处理
- **WHEN** 香港官方通知、兽医报告、装备更新或 racecard update 进入新闻池
- **THEN** 系统 SHALL 允许其进入站内自动发布门禁
- **AND** 系统 SHALL 根据通知重要性决定是否具备 QQ 资格

### Requirement: 英文核心术语门禁必须支持可接受翻译差异
系统 SHALL 在判断可信核心英文赛事、马名、骑师或练马师是否缺失时，允许已知中文译名、原文、alias、合理全角/半角和大小写差异作为保留形式。系统 MUST NOT 因可接受保留形式存在而生成 `core_term_missing` blocker。

#### Scenario: 原文保留不阻断
- **WHEN** 英文文章命中可信赛事术语 `Princess Of Wales's Stakes`
- **AND** 发布稿保留该英文原文或已知别名
- **THEN** 系统 SHALL NOT 生成该术语的 `core_term_missing` blocker

#### Scenario: 可信专名完全缺失仍阻断
- **WHEN** 英文文章命中可信赛事术语 `Belmont Stakes`
- **AND** 发布稿缺少中文译名、英文原文和可接受别名
- **THEN** 系统 SHALL 生成 `core_term_missing` blocker

#### Scenario: 非术语忽略仅豁免实际命中的原文
- **WHEN** 同一术语记录包含多个原文或 alias
- **AND** 其中一个 alias 被配置为普通词忽略项
- **AND** 当前文章实际命中的是另一个未被忽略的可信专名
- **THEN** 系统 MUST 继续校验实际命中的可信专名
- **AND** 系统 MUST NOT 因同记录内存在被忽略 alias 而绕过 `core_term_missing` 门禁

### Requirement: 地区归属结果必须参与门禁和策略判断
系统 SHALL 使用文章主地区和相关地区判断英文术语地区过滤、自动发布 allowlist、内容类别策略和 QQ 资格。跨地区文章中的相关地区术语 MUST NOT 因不等于主地区而被简单排除。

#### Scenario: 相关地区术语可参与校验
- **WHEN** 一篇主地区为英国、相关地区为法国的英文文章命中法国赛事术语
- **THEN** 系统 SHALL 允许该法国赛事术语参与可信核心术语校验
- **AND** 系统 SHALL NOT 仅因文章主地区是英国而记录 `term_region_excluded`

#### Scenario: 不相关地区术语仍排除
- **WHEN** 一篇英国/法国多地区文章命中香港马名普通词
- **AND** 香港不在文章主地区或相关地区中
- **THEN** 系统 SHALL 继续按地区不匹配排除该术语或降级为 info

### Requirement: 重处理必须同时重算地区归属和英文门禁
系统 SHALL 提供受控重处理入口，对近期候选重新计算主地区、相关地区、内容类别和英文门禁。重处理 MUST 支持 dry-run 和 commit；commit 不得直接公开发布文章，只能让完整门禁通过的文章重新进入发布候选。

#### Scenario: dry-run 输出地区和门禁变化
- **WHEN** 运维人员 dry-run 重处理近期英国、香港、法国或美国候选
- **THEN** 系统 SHALL 输出主地区变化、相关地区变化、内容类别、普通词降级、可信专名 blocker 和预计可恢复候选
- **AND** 系统 SHALL NOT 修改文章状态

#### Scenario: commit 不直接公开
- **WHEN** 运维人员提交重处理
- **AND** 某文章重处理后通过完整门禁
- **THEN** 系统 SHALL 允许该文章重新进入发布候选
- **AND** 系统 SHALL NOT 在重处理命令内直接设置为公开已发布
