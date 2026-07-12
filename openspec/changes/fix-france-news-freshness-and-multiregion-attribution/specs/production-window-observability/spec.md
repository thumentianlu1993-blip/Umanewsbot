## ADDED Requirements

### Requirement: 法国来源窗口必须展示最新稿发现与时间可信度 <!-- id: req-source-freshness-observability -->
系统 SHALL 在来源和窗口观测中区分日期倒序候选、历史过滤、重复、时间不可信和解析失败，并展示最近真实来源发布时间。

#### Scenario: TDN 全部为历史结果
- **WHEN** TDN 法国来源本轮候选全部超过新鲜度
- **THEN** 系统 SHALL 记录 `stale_published_at` 数量和最近候选真实时间
- **AND** MUST NOT 仅显示笼统的成功 0 新增

#### Scenario: France Galop 时间不可信
- **WHEN** France Galop 文章无法解析官方时间
- **THEN** 窗口 SHALL 记录 `published_at_unverified`
- **AND** 后台 SHALL 提供文章定位入口

### Requirement: 窗口必须展示翻译恢复状态 <!-- id: req-translation-retry-observability -->
系统 SHALL 展示本窗口新发生的可恢复失败、等待重试、重试成功、永久失败和重试耗尽数量，并提供失败文章快速处理入口。

#### Scenario: 429 等待重试
- **WHEN** 一篇法国文章因 `429` 进入自动退避
- **THEN** 后台 SHALL 显示错误类别、已用次数和下次重试时间

#### Scenario: 重试后恢复生产
- **WHEN** 翻译重试成功并重新进入评分链路
- **THEN** 窗口 SHALL 记录该文章由翻译恢复进入候选

### Requirement: 窗口必须展示归属决策和相关地区可见性 <!-- id: req-attribution-observability -->
系统 SHALL 分别统计主地区候选、相关地区可见文章、source fallback、主地区变化、`needs_review` 和过度扩散阻断。0 发布原因 MUST 能区分没有稿、稿件归属待复核、翻译失败和门禁阻断。

#### Scenario: 法国稿被归属待复核阻断
- **WHEN** 本窗口有法国相关候选但归属状态为 `needs_review`
- **THEN** 法国窗口 SHALL 记录 `attribution_needs_review`
- **AND** 提供对应文章和证据入口

#### Scenario: 相关地区已有公开内容
- **WHEN** 法国窗口没有新发布但已有主地区为其他地区的法国相关公开文章
- **THEN** 窗口 SHALL 记录相关地区可见数量
- **AND** MUST NOT 将其误报为重复发布成功

### Requirement: 多地区灰度必须有可回滚运营视图 <!-- id: req-rollout-observability -->
系统 SHALL 展示当前归属规则版本、归属模式、相关地区查询开关、gold set 指标、最近生产 dry-run 和灰度阶段，并提供对应的 runbook 操作入口或命令。

#### Scenario: 指标未达标
- **WHEN** 当前规则版本未达到任一生产门槛
- **THEN** 后台 SHALL 明确显示 no-go
- **AND** 不得把开关关闭解释为来源故障

#### Scenario: 灰度异常快速回滚
- **WHEN** 运营发现错配、重复展示或 QQ 路由异常
- **THEN** 运行手册 SHALL 提供先关相关查询、再关归属写入的步骤
- **AND** 关闭操作 MUST 不影响单地区抓取和发布
