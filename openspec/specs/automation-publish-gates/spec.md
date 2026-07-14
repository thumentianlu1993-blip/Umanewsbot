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

### Requirement: 榜单二次命中必须唤醒未发布文章
系统 SHALL 在同一篇未发布文章从普通来源升级为榜单来源时执行榜单唤醒流程。榜单唤醒 SHALL 将低分忽略、价值不足转人工、待翻译或翻译失败文章重新送回正常自动化流水线，但不得直接发布文章。

#### Scenario: 低分忽略文章进入榜单
- **WHEN** 一篇未发布文章因分数低或发布价值不足被标记为 ignored
- **AND** 后续抓取确认该文章从普通来源升级为榜单来源
- **THEN** 系统 SHALL 将该文章从低分忽略状态唤醒
- **AND** 系统 SHALL 记录榜单唤醒原因和唤醒时间

#### Scenario: 价值不足转人工文章进入榜单
- **WHEN** 一篇未发布文章因价值不足进入 manual_review_required
- **AND** 该文章没有人工拒绝、撤回或当前 blocker
- **AND** 后续抓取确认该文章从普通来源升级为榜单来源
- **THEN** 系统 SHALL 重新评估该文章的自动发布资格
- **AND** 系统 SHALL 保留榜单唤醒原因供后台和窗口账本追溯

#### Scenario: 已发布文章进入榜单
- **WHEN** 一篇已发布文章后续从普通来源升级为榜单来源
- **THEN** 系统 SHALL NOT 再次发布该文章
- **AND** 系统 MAY 继续按现有 QQ 自动推送逻辑尝试补推

### Requirement: 榜单唤醒必须重试翻译并重新评分
系统 SHALL 在榜单唤醒后根据文章当前翻译状态执行受控翻译重试或重新评分。翻译未成功的文章必须先重试翻译；翻译已成功的文章必须重新评分，使榜单来源高价值信号参与自动发布判断。

#### Scenario: 翻译失败文章进入榜单
- **WHEN** 一篇 translation_failed 的未发布文章后续升级为榜单来源
- **THEN** 系统 SHALL 自动派发一次翻译重试
- **AND** 系统 SHALL 记录该重试由榜单唤醒触发

#### Scenario: 待翻译文章进入榜单
- **WHEN** 一篇尚未成功翻译的未发布文章后续升级为榜单来源
- **THEN** 系统 SHALL 确保该文章进入翻译任务
- **AND** 系统 SHALL NOT 在翻译成功前将该文章标记为可自动发布

#### Scenario: 已翻译低分文章进入榜单
- **WHEN** 一篇已成功翻译但低分或价值不足的未发布文章后续升级为榜单来源
- **THEN** 系统 SHALL 重新执行自动评分
- **AND** 命中高价值来源规则且无 blocker 的文章 SHALL 能够达到自动发布候选所需分数下限

### Requirement: 榜单唤醒不得绕过硬门禁和人工终态
系统 MUST 保持榜单唤醒与硬门禁、人工终态和重复内容阻断相互独立。榜单信号只能触发重新处理，不能覆盖人工明确结论或发布校验 blocker。

#### Scenario: 人工拒绝文章进入榜单
- **WHEN** 一篇人工明确拒绝的文章后续升级为榜单来源
- **THEN** 系统 SHALL NOT 自动唤醒该文章
- **AND** 系统 SHALL NOT 自动发布该文章

#### Scenario: 已撤回文章进入榜单
- **WHEN** 一篇已撤回文章后续升级为榜单来源
- **THEN** 系统 SHALL NOT 自动唤醒该文章
- **AND** 系统 SHALL NOT 自动发布该文章

#### Scenario: 存在 blocker 的文章进入榜单
- **WHEN** 一篇文章存在正文缺失、核心术语缺失、高度重复或其他 blocker
- **AND** 后续抓取确认该文章升级为榜单来源
- **THEN** 系统 SHALL 保留 blocker 阻断结果
- **AND** 系统 SHALL NOT 仅因榜单信号将其标记为可自动发布

#### Scenario: 重复内容文章进入榜单
- **WHEN** 一篇 duplicate 状态或高度重复 blocker 文章后续升级为榜单来源
- **THEN** 系统 SHALL NOT 自动复活该文章
- **AND** 系统 SHALL 保留重复内容原因

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

### Requirement: 发布门禁必须校验正文与机器实体类型一致
系统 SHALL 使用文章级实体解析结果检查翻译术语、机器马名标签和自动马匹关联。批量校验上下文 SHALL 预计算并携带同一实体结果及接受术语 ID，不得在校验阶段重新运行旧识别。人物或普通词不得以马名形式进入任一机器输出；同一已接受马名在正文、标签和关联中的类型 SHALL 一致。

#### Scenario: 普通词批量误标
- **WHEN** 一篇文章的全部马名标签都来自被解析为普通词的跨度
- **THEN** 系统 SHALL 将这些标签视为机器实体不一致
- **AND** 自动发布 SHALL 在完成机器标签重算前阻止或转人工处理

#### Scenario: 人物被标记成马
- **WHEN** `Grace Hamilton` 被解析为人物但机器标签或自动关联包含内部 `Hamilton` 马名
- **THEN** 系统 SHALL 记录实体类型不一致问题
- **AND** 该马名标签或自动关联 SHALL NOT 进入最终机器输出

### Requirement: 实体修复后必须支持受控重新校验
系统 SHALL 允许对显式文章 ID 在实体、翻译和机器标签修复后重新运行完整发布校验。重新校验 MUST 保留其他真实 blocker，不得因清除误识别而自动绕过人工终态或直接重复发布。

#### Scenario: 误识别清除后仍有其他 blocker
- **WHEN** 文章的普通词马名误识别已清除但仍存在其他 blocker
- **THEN** 系统 SHALL 保留其他 blocker 和人工处理状态

#### Scenario: 已发布文章只更新内容
- **WHEN** 已发布问题文章完成实体修复、重译和重新校验
- **THEN** 系统 SHALL 保持既有公开状态和发布时间
- **AND** 系统 SHALL NOT 重新占用发布配额或创建 QQ delivery
