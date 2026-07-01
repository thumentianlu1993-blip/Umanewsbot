# automation-publish-gates Specification

## Purpose
定义新闻自动发布前的评分、门禁、重复检测、告警和后台展示规则，确保高价值新闻可以稳定自动进入前台，同时保留可审计的人工接管边界。
## Requirements
### Requirement: 自动发布门禁必须区分严重级别
系统 SHALL 使用结构化校验 issue 描述自动发布门禁结果，并且每个 issue 必须包含稳定代码、严重级别、展示文案和可审计 payload。严重级别必须至少包含 `blocker`、`warning` 和 `info`。

#### Scenario: blocker 阻断自动发布
- **WHEN** 自动化校验结果包含 `blocker`
- **THEN** 系统不得将文章标记为可自动发布，并必须把文章转入人工审核或重复内容状态

#### Scenario: warning 初期不阻断自动发布
- **WHEN** 自动化校验结果不包含 `blocker` 但包含 `warning`
- **THEN** 系统 SHALL 允许文章继续进入自动发布就绪状态，并记录 warning 明细

#### Scenario: info 仅作为诊断
- **WHEN** 自动化校验结果仅包含 `info`
- **THEN** 系统 SHALL 记录诊断信息，并不得因该信息改变文章分流或发布状态

### Requirement: 基准翻译稿可作为自动发布内容源
系统 SHALL 支持通过配置关闭 AI 改写前置，并使用基准翻译稿作为自动发布内容源。关闭 AI 改写时，系统必须跳过改写任务，但仍执行评分、基础门禁、warning 记录和自动发布批次。

#### Scenario: 关闭 AI 改写后跳过改写任务
- **WHEN** `AUTO_REWRITE_ENABLED=false` 且文章评分进入自动候选
- **THEN** 系统 SHALL 不调用 AI 改写任务，并使用基准中文标题、摘要和正文执行自动发布门禁

#### Scenario: 基准翻译稿通过基础门禁
- **WHEN** 文章翻译成功，具有可展示标题、摘要、正文和原文链接，且不存在 blocker
- **THEN** 系统 SHALL 将文章标记为可自动发布

#### Scenario: 基准翻译稿缺少正文
- **WHEN** 文章没有可展示正文
- **THEN** 系统 SHALL 生成 `missing_body` blocker，并转入人工审核

### Requirement: 长采访、引语和数字省略不得作为硬性门禁
系统 SHALL 不得仅因文章为长采访、引语较多或改写/发布稿省略部分数字而阻断自动发布。这些情况必须降级为 warning 或 info。

#### Scenario: 引语较多不阻断
- **WHEN** 文章包含较多引语且不存在其他 blocker
- **THEN** 系统 SHALL 记录引语 warning，并允许文章继续进入自动发布就绪状态

#### Scenario: 数字省略不阻断
- **WHEN** 系统发现发布稿省略部分原文数字且不存在其他 blocker
- **THEN** 系统 SHALL 记录数字省略 warning 或 info，并允许文章继续进入自动发布就绪状态

### Requirement: 高价值来源必须支持配置化评分放行
系统 SHALL 支持配置高价值来源规则。命中高价值来源的文章在通过硬性 blocker 检查后，必须能够直接进入自动候选或获得自动候选所需的分数下限。

#### Scenario: netkeiba 访问量榜进入自动候选
- **WHEN** 文章来源为 `netkeiba` 且来源模式为 `access`，并且没有 blocker
- **THEN** 系统 SHALL 将文章视为高价值来源候选，使其通过评分阶段进入自动候选

#### Scenario: netkeiba 注目数榜进入自动候选
- **WHEN** 文章来源为 `netkeiba` 且来源模式为 `attention`，并且没有 blocker
- **THEN** 系统 SHALL 将文章视为高价值来源候选，使其通过评分阶段进入自动候选

#### Scenario: 高价值来源不绕过 blocker
- **WHEN** 高价值来源文章正文为空或疑似乱码
- **THEN** 系统 SHALL 生成 blocker，并不得仅因来源高价值而进入自动发布就绪状态

### Requirement: 高价值 warning 必须触发邮件告警
系统 SHALL 在高价值文章出现 warning 时发送邮件告警。warning 初期不阻断自动发布，但告警必须让工作人员能快速打开候选详情并判断是否需要人工接管。

#### Scenario: 高价值文章有 warning
- **WHEN** 文章评分达到高价值阈值或命中高价值来源，校验结果包含 warning，且不存在 blocker
- **THEN** 系统 SHALL 向配置的通知邮箱发送告警邮件，并记录通知日志

#### Scenario: 邮件包含审阅所需上下文
- **WHEN** 系统发送高价值 warning 邮件
- **THEN** 邮件内容 MUST 包含文章标题、候选详情链接、原文链接、来源、分数、warning 列表和当前发布状态

#### Scenario: warning 邮件缺少收件人配置
- **WHEN** warning 邮件开关开启但没有配置收件人
- **THEN** 系统 SHALL 记录 skipped 通知日志，并不得阻断自动发布

### Requirement: 重复内容必须阻断自动重复发表
系统 SHALL 在自动发布前检测待发布文章与已发布文章的主要内容重合度。高度重复的文章必须被阻断，不得重复进入前台；中等相似的文章必须转入人工审核。

#### Scenario: 高度重复文章被阻断
- **WHEN** 待发布文章与近期待发布或已发布文章的标题、摘要和正文主要内容高度重合
- **THEN** 系统 SHALL 生成 `duplicate_content` blocker，将该文章标记为重复内容状态，并记录相似文章、相似度和原因

#### Scenario: 中等相似文章转人工
- **WHEN** 待发布文章与已发布文章相似度处于人工判断区间
- **THEN** 系统 SHALL 生成 `possible_duplicate_content` blocker，转入人工审核，并展示相似文章链接和相似度

#### Scenario: 仅共享马名或比赛名不算重复
- **WHEN** 两篇文章仅共享马名、比赛名或赛事日期，但整体事实角度和正文内容不高度重合
- **THEN** 系统 SHALL 不得仅因实体相同标记为重复内容

### Requirement: 后台必须展示门禁明细
系统 SHALL 在候选新闻列表、候选详情和自动化日志中展示自动发布门禁结果，区分 blocker、warning 和 info，并保留评分摘要与门禁结论的差异。

#### Scenario: 评分通过但存在 warning
- **WHEN** 文章评分达到自动候选且存在 warning
- **THEN** 候选详情 SHALL 展示评分通过、warning 列表和当前是否可自动发布

#### Scenario: 评分通过但被 blocker 阻断
- **WHEN** 文章评分达到自动候选但存在 blocker
- **THEN** 候选列表和详情 SHALL 明确展示 blocker 原因，而不得只显示评分阶段的自动候选摘要

### Requirement: 自动发布必须支持地区和来源灰度策略
系统 SHALL 支持按地区和来源控制文章是否允许进入自动发布。未被允许自动发布的地区或来源，文章 MAY 继续完成抓取、翻译、评分和门禁检查，但 MUST 转入人工审核或保持待审核状态，而不得自动公开。

#### Scenario: 未允许地区转人工审核
- **WHEN** 一篇英国、法国、美国或中国香港文章完成翻译和自动评分
- **AND** 该文章地区未被自动发布策略允许
- **THEN** 系统 SHALL 将该文章转入人工审核或待审核状态
- **AND** 不得将其标记为自动发布就绪

#### Scenario: 非日本新闻默认不自动发布
- **WHEN** 生产未显式配置某个非日本地区或来源允许自动发布
- **AND** 该地区文章完成翻译和自动评分
- **THEN** 系统 SHALL 按人工审核优先处理该文章
- **AND** 不得仅因评分达到阈值自动公开

#### Scenario: 允许来源可进入自动发布
- **WHEN** 一篇国际新闻的地区和来源均被自动发布策略允许
- **AND** 文章不存在 blocker 且满足自动发布门禁
- **THEN** 系统 SHALL 允许该文章进入自动发布就绪状态

#### Scenario: 来源策略不绕过 blocker
- **WHEN** 某国际来源被自动发布策略允许
- **AND** 文章存在正文缺失、公开 URL 缺失、核心术语缺失或重复内容 blocker
- **THEN** 系统 SHALL 阻断自动发布并转入人工处理

### Requirement: 自动发布批次必须支持地区上限
系统 SHALL 支持为多地区常态生产配置每轮或每日自动发布上限，避免某一地区或某一来源在短时间内刷屏公开首页和 QQ 群。

#### Scenario: 地区每轮上限生效
- **WHEN** 自动发布批次中某地区可发布文章数量超过该地区每轮上限
- **THEN** 系统 SHALL 只自动发布不超过该地区上限的文章
- **AND** 其余文章 SHALL 保持可后续处理状态

#### Scenario: 地区每日上限生效
- **WHEN** 某地区当天自动发布数量已达到每日上限
- **THEN** 系统 SHALL 不再自动发布该地区新的文章
- **AND** 这些文章 SHALL 转入人工审核或等待下一窗口

#### Scenario: 日本既有自动发布不被国际上限拖慢
- **WHEN** 国际地区达到自动发布上限
- **THEN** 系统 SHALL NOT 因该上限阻断符合既有策略的日本文章自动发布

#### Scenario: 自动发布批次选择保持有界
- **WHEN** 自动发布批次按地区上限选择候选文章
- **THEN** 系统 SHALL 使用有限候选集、聚合计数或数据库过滤完成选择
- **AND** 不得在内存中无界加载全部历史文章

### Requirement: 国际新闻自动发布必须保留可解释原因
系统 SHALL 在国际新闻分流、转人工、自动发布或跳过时记录地区、来源、策略命中、上限命中和门禁结果，便于工作人员解释为什么某地区没有自动公开。

#### Scenario: 地区未允许原因可见
- **WHEN** 国际新闻因地区未允许自动发布而转人工
- **THEN** 后台或自动化日志 SHALL 展示地区未允许、来源、文章分数和当前策略

#### Scenario: 上限命中原因可见
- **WHEN** 国际新闻因地区每轮或每日上限未被自动发布
- **THEN** 后台或自动化日志 SHALL 展示命中的上限类型和当前计数

### Requirement: 窗口自动发布硬门禁
系统 SHALL 使用统一硬门禁判断文章是否可进入窗口自动发布。

#### Scenario: 硬门禁阻断
- **WHEN** 某文章翻译失败、无中文正文、正文过短、明显乱码、非赛马内容、URL 不可访问或重复组已有赢家
- **THEN** 系统 SHALL 阻断该文章自动发布并保存结构化 blocker

#### Scenario: 预览和执行一致
- **WHEN** 运营预览发布窗口后真实执行该窗口
- **THEN** 系统 SHALL 使用同一硬门禁服务生成一致的 blocker 结果

### Requirement: 保底发布分数边界
系统 SHALL 允许地区软下限保底发布低于高价值阈值但不低于 45 分的文章。

#### Scenario: 低于高价值但满足保底
- **WHEN** 某地区窗口没有高价值文章但存在 45 分及以上且通过硬门禁的候选
- **THEN** 系统 SHALL 允许将该文章作为 `region_minimum_fill` 自动发布

#### Scenario: 低于 45 分
- **WHEN** 某候选文章分数低于 45
- **THEN** 系统 SHALL 不自动发布该文章

### Requirement: 自动发布去重赢家
系统 SHALL 在自动发布前执行地区内强去重和跨地区弱去重，并保存赢家与落选原因。

#### Scenario: 地区内重复报道
- **WHEN** 同一地区多篇候选文章报道同一事件
- **THEN** 系统 SHALL 只自动发布最高优先级文章，并将其他文章记录为 `dedup_loser`

#### Scenario: 跨地区高度重复
- **WHEN** 不同地区候选文章内容高度重复且全站额度紧张
- **THEN** 系统 SHALL 优先发布最高分或最相关地区文章，并保存跨地区去重解释

### Requirement: 自动发布配额账本
系统 SHALL 使用持久化配额账本控制地区窗口、地区小时和全站小时自动发布数量。

#### Scenario: 并发发布窗口竞争
- **WHEN** 两个 worker 并发尝试占用同一地区小时发布额度
- **THEN** 系统 SHALL 通过事务和配额账本防止超过配置上限

#### Scenario: 配额不足
- **WHEN** 某候选文章通过硬门禁但地区或全站配额不足
- **THEN** 系统 SHALL 不发布该文章并保存 `quota_limited` 原因
