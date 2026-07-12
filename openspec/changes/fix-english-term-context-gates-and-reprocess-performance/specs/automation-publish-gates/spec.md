## MODIFIED Requirements

### Requirement: 英文术语门禁必须按上下文区分普通词和专有名词
系统 SHALL 对英文来源文章中每一次正式术语或 alias 命中分别提取上下文，并判断该次命中是普通英文词、真实赛马专有名词还是不确定用法。合法存在的单词型马名 MUST 保留在术语库中；`term_type=horse` 不得单独作为该次命中属于专名的充分证据。高置信普通英文词不得生成自动发布 blocker；真实核心专名仍 MUST 按核心术语缺失规则阻断；不确定命中 MUST 按文章位置和重要性分层处理。

#### Scenario: 同一个词同时作为马名和普通词
- **WHEN** 英文文章包含类似 `Brilliant was brilliant at Sha Tin` 的文本
- **AND** 第一次命中有马匹主语或结构化实体证据，第二次命中处于普通形容词位置
- **THEN** 系统 MUST 将第一次命中分类为专有名词或高置信马名
- **AND** 系统 MUST 将第二次命中分类为普通词
- **AND** 门禁只对第一次命中执行译名或原文保留检查

#### Scenario: 单词型正式马名在普通上下文中不阻断
- **WHEN** 术语库存在名为 `Brilliant`、`Something`、`Threat` 或同类单词型正式马名
- **AND** 当前实际命中位于 `a brilliant winner`、`something went wrong`、`posed a threat` 或等价普通语法上下文
- **THEN** 系统 SHALL 将该次命中分类为 `common_word`
- **AND** 系统 SHALL NOT 仅因术语记录类型为 `horse` 生成 `core_term_missing` blocker

#### Scenario: 单词型真实马名继续保护
- **WHEN** 单词型正式马名作为参赛马、赛果马匹、`won / finished / ridden by / trained by` 等关系中的实体出现
- **AND** 中文发布稿未保留正式译名、实际原文或可接受 alias
- **THEN** 系统 MUST 将该次命中作为真实专名参与校验
- **AND** 核心位置缺失时 MUST 继续生成 `core_term_missing` blocker

#### Scenario: 标题大写不是充分证据
- **WHEN** 候选词仅因英文标题格式而首字母大写
- **AND** 没有马匹关系、结构化参赛记录或其他强实体证据
- **THEN** 系统 MUST NOT 仅凭大小写将其高置信分类为专有名词

#### Scenario: 不确定核心命中保守处理
- **WHEN** 系统无法确定标题、摘要或首段中的单词型命中是马名还是普通词
- **AND** 中文发布稿未保留正式译名、实际原文或可接受 alias
- **THEN** 系统 MUST 保持 blocker 或转入人工审核
- **AND** issue payload MUST 记录 `uncertain`、置信度、命中位置和不确定原因

#### Scenario: 不确定背景命中不单独阻断
- **WHEN** 不确定命中只位于正文背景段落
- **AND** 文章不存在该术语的高置信核心专名命中
- **THEN** 系统 SHALL 记录 warning
- **AND** 系统 SHALL NOT 仅因该背景命中阻断自动发布

#### Scenario: 已保留可接受形式时跳过分类阻断
- **WHEN** 中文稿已包含正式译名、文章实际命中的英文原文、同语言 alias 或规范化等价形式
- **THEN** 系统 SHALL 判定该术语已保留
- **AND** 系统 SHALL NOT 因上下文分类不确定而生成 `core_term_missing`

#### Scenario: 地区过滤优先于语义判定
- **WHEN** 英文文章命中不属于文章主地区、相关地区或全局范围的正式术语
- **THEN** 系统 SHALL 继续按地区过滤规则排除或降级该术语
- **AND** 系统 SHALL NOT 为已排除命中执行高成本上下文分类

#### Scenario: 命中级分类结果可审计
- **WHEN** 系统分类任一英文术语命中
- **THEN** validation details 或 issue payload MUST 包含术语/alias ID、实际文本、字段和位置、有限上下文、分类、置信度、原因码及使用的实体证据
- **AND** 系统 MUST 能在同一术语存在多个命中时分别展示结果

#### Scenario: 页面结构和样板文本不参与术语判断
- **WHEN** 普通英文词只出现在 HTML 属性、脚本、样式、导航、推荐卡片、嵌入元数据或其他非正文样板中
- **THEN** 系统 MUST NOT 将其作为正文术语命中
- **AND** 分类输入 MUST 只包含标题和清洗后的可见文章正文

#### Scenario: 灰度模式互斥且默认关闭
- **WHEN** 上下文门禁模式为 `off`
- **THEN** 系统 MUST 完全沿用旧门禁判定
- **WHEN** 模式为 `shadow`
- **THEN** 系统 SHALL 记录新旧判定差异但 MUST NOT 因新判定修改文章门禁或工作流状态
- **WHEN** 模式为 `enforce`
- **THEN** 系统 SHALL 使用新上下文分类决定英文术语门禁
- **AND** 非法模式值 MUST 被拒绝或回退到保守的 `off`

### Requirement: 旧英文核心术语 blocker 必须支持优化版完整重校验
系统 SHALL 提供有界、可续跑且互斥的重校验能力，对指定地区、时间窗、来源和旧 `core_term_missing` 候选执行完整自动发布门禁 dry-run。重校验 MUST 先筛选候选 ID，再只加载选中正文，并在整个批次复用同一批次校验上下文；dry-run 与 commit MUST 复用相同判定服务。每次运行 MUST 在数据库中留下可审计、跨容器持久化的运行记录。

#### Scenario: dry-run 不写生产数据
- **WHEN** 运维人员执行旧英文核心术语 blocker 重校验 dry-run
- **THEN** 系统 MUST 输出候选文章 ID、通过列表、仍阻断列表、blocker、warning 和命中级分类明细
- **AND** 系统 MUST 不修改 `NewsArticle` 状态、门禁字段、发布时间、发布窗口或 QQ delivery
- **AND** 系统 SHALL 只写入独立重校验运行记录、单例租约和有界审核结果

#### Scenario: 重校验候选集有界
- **WHEN** 运维人员执行重校验
- **THEN** 系统 MUST 要求或应用地区、时间窗、来源、稳定游标、数量上限和最大执行时间中的有界组合
- **AND** 系统 MUST 只完整加载当前存在 `core_term_missing` 且未进入人工终态的选中候选
- **AND** 系统 MUST NOT 默认遍历全部历史人工审核文章

#### Scenario: 批次复用术语索引
- **WHEN** 同一重校验批次处理多篇英文文章
- **THEN** 系统 MUST 只为固定术语快照构建一次规范化匹配索引
- **AND** 系统 MUST NOT 为每篇文章重新遍历和编译完整术语库
- **AND** 系统 MUST 批量复用结构化实体证据和重复检测候选语料，避免逐篇重复查询

#### Scenario: 达到执行时间后可续跑
- **WHEN** 重校验达到 `max_seconds` 或等价执行预算
- **THEN** 系统 SHALL 安全停止且不丢失已完成 dry-run 结果
- **AND** 输出 MUST 包含停止原因、已扫描数、已完成数和编码固定 `window_start/window_end` 及 `(first_seen_at,id)` 的下一稳定游标
- **AND** 后续运行 MUST 在相同选择器下无重复、无遗漏地续跑
- **AND** 后续运行 MUST 复用首次运行的绝对时间窗口，不得因当前时间推进漏掉旧候选或混入窗口结束后到达的新文章

#### Scenario: 任意重校验并发运行被拒绝
- **WHEN** 任意地区已有未过期的重校验租约
- **THEN** 后续进程 MUST 在扫描正文前退出
- **AND** 系统 MUST 返回当前 run、数据库租约和可重试时间，不得并发占用生产 CPU
- **AND** 只有租约过期后才允许事务化接管，旧 owner MUST NOT 释放或覆盖新 owner 的租约

#### Scenario: dry-run 结果跨容器持久化
- **WHEN** dry-run 完成后应用容器被重建或重启
- **THEN** 选择器、规则和术语快照、候选输入指纹、结果摘要、manifest SHA、统计和续跑游标 MUST 仍可从数据库运行记录恢复
- **AND** JSON 文件 SHALL 仅作为可选导出而不是 commit 的唯一事实来源

#### Scenario: commit 拒绝全局快照漂移
- **WHEN** commit 引用的 dry-run 之后规则版本、相关设置或有效术语/alias 快照发生变化
- **THEN** 系统 MUST 拒绝整个 commit 且不修改任何文章
- **AND** 运行记录 MUST 标明实际与期望的快照摘要

#### Scenario: commit 跳过单篇文章漂移
- **WHEN** 全局快照未变化但某篇文章的源文本、发布文本、门禁或工作流关键状态在 dry-run 后变化
- **THEN** 系统 MUST 跳过该文章并记录漂移原因
- **AND** 系统 MUST NOT 覆盖该文章的新状态

#### Scenario: commit 只恢复完整通过文章
- **WHEN** 运维人员使用 dry-run run ID 和匹配的 manifest SHA 执行 commit
- **THEN** 系统 MUST 仅对完整门禁通过的文章应用校验结果并恢复为发布候选
- **AND** 系统 MUST 不直接公开文章、不创建 QQ delivery、不绕过窗口去重和配额
- **AND** 已漂移或仍有 blocker 的文章 MUST 跳过并保留原因
- **AND** 每个写入批次的文章状态、门禁结果、自动化日志和恢复时间 MUST 在同一数据库事务中提交或回滚

#### Scenario: 重校验输出产量漏斗
- **WHEN** 运维人员完成一批 dry-run 或 commit
- **THEN** 输出 MUST 分别统计普通词降级数、uncertain 数、真实专名 blocker 数、完整通过数、恢复候选数和最终非本命令负责的待发布数
- **AND** 系统 MUST NOT 把完整通过数直接标记为已公开数量

#### Scenario: 生产等价性能门槛
- **WHEN** 上线前使用固定 100 篇真实等价候选执行 dry-run 基准
- **THEN** 包含候选选择、批次上下文构建、完整门禁、重复检测和运行结果持久化的执行 MUST 在 60 秒内完成
- **AND** 峰值 RSS 增量 MUST 不超过 256 MiB
- **AND** 总 SQL MUST 不超过 35 条，术语索引 MUST 只构建一次，赛事实体/外部马名 alias/额外马名术语/重复语料批量预取 MUST 分别不超过 `2/1/0/1` 次
- **AND** 测试或验收 MUST 记录查询数、索引构建次数、实体/重复语料预取次数、处理数、耗时和内存证据
