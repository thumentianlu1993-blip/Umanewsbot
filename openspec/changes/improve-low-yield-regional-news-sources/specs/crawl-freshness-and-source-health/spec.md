## ADDED Requirements

### Requirement: 抓取任务必须保存结构化产出摘要 <!-- id: req-crawl-structured-yield -->
系统 SHALL 为国际新闻抓取保存有界结构化产出摘要，至少包含 listing、详情成功/失败、过期、非赛马、重复和创建计数；摘要不得保存无界 HTML 或正文。

#### Scenario: 部分详情解析失败
- **WHEN** 一轮 listing 有条目，部分详情成功、部分详情失败
- **THEN** CrawlJob SHALL 记录 detail_attempted、detail_succeeded、detail_failed 和 created
- **AND** 首个错误样本 SHALL 被截断到有界长度

#### Scenario: 全部条目为旧稿或重复
- **WHEN** 一轮没有创建文章，但条目全部被 stale 或 duplicate 过滤
- **THEN** 来源健康 SHALL 展示对应计数
- **AND** 不得把该结果误报为 adapter 解析失败

### Requirement: 来源只读探测不得写业务数据 <!-- id: req-source-probe-readonly -->
系统 SHALL 为候选和现有来源提供有界只读探测。探测 MUST NOT 创建 `CrawlJob`、`NewsArticle`、生产窗口或改变 `NewsSource` 状态。

#### Scenario: 探测现有香港来源
- **WHEN** 运维人员对香港来源执行 listing/详情只读 probe
- **THEN** 系统 SHALL 输出 HTTP、样本、日期、解析和重复证据
- **AND** 数据库业务表计数 SHALL 保持不变

#### Scenario: 探测遇到访问限制
- **WHEN** probe 返回 403、429、反机器人页或 TLS/超时错误
- **THEN** 系统 SHALL 记录稳定错误类别并停止扩大请求
- **AND** 不得自动停用或批准生产来源
