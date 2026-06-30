## ADDED Requirements

### Requirement: 启用新闻来源必须支持通用常态轮询
系统 SHALL 提供通用新闻来源轮询任务，用于按 `NewsSource.enabled`、`crawl_interval_minutes`、最近抓取时间和来源类型选择到期新闻来源并触发抓取。该任务 MUST 可通过配置关闭，且 MUST 不影响现有日本固定抓取任务的错峰语义。

#### Scenario: 到期启用来源被轮询
- **WHEN** 某启用新闻来源的最近成功或失败抓取时间早于当前时间减去 `crawl_interval_minutes`
- **AND** 该来源被包含在通用轮询允许范围内
- **THEN** 通用轮询任务 SHALL 为该来源触发一次抓取

#### Scenario: 未到期来源不抓取
- **WHEN** 某启用新闻来源最近抓取时间仍在 `crawl_interval_minutes` 内
- **THEN** 通用轮询任务 SHALL 跳过该来源

#### Scenario: 停用来源不抓取
- **WHEN** 某来源 `enabled=false`
- **THEN** 通用轮询任务 SHALL NOT 为该来源触发抓取

#### Scenario: 从未运行来源按安全上限进入轮询
- **WHEN** 某启用来源尚无 `last_crawl_at` 且没有已完成 `CrawlJob`
- **AND** 该来源被包含在通用轮询允许范围内
- **THEN** 通用轮询任务 SHALL 视其为待首轮抓取候选
- **AND** 仍 MUST 受每轮最大来源数和同源运行中检查约束

#### Scenario: 固定调度来源不重复抓取
- **WHEN** netkeiba 新着顺、访问量榜、注目数榜或 JRA 仍由固定 Celery Beat 任务调度
- **THEN** 通用轮询任务 SHALL 默认跳过这些固定调度来源，避免同一来源重复抓取

### Requirement: 通用轮询必须避免同一来源并发抓取
系统 SHALL 在触发来源抓取前检查该来源是否存在仍在运行且未超时的 `CrawlJob`。若存在运行中任务，系统 MUST 跳过该来源并记录跳过原因。

#### Scenario: 运行中来源被跳过
- **WHEN** 某来源存在最新 `CrawlJob.status=started` 且未超过运行超时阈值
- **THEN** 通用轮询任务 SHALL 跳过该来源
- **AND** 不得为同一来源创建新的抓取任务

#### Scenario: 陈旧运行中来源不无限阻塞
- **WHEN** 某来源最新 `CrawlJob.status=started` 已超过运行超时阈值
- **THEN** 通用轮询任务 SHALL 将该来源作为疑似卡住记录在结果中
- **AND** 是否重新触发抓取 MUST 由明确配置或后续人工处理决定

### Requirement: 通用轮询必须控制每轮抓取规模
系统 SHALL 支持配置通用轮询每轮最多处理的来源数量，并按地区、来源优先级、到期时间或等价稳定规则选择来源，避免一次任务同时触发所有国际来源。

#### Scenario: 每轮来源数受限
- **WHEN** 到期启用来源数量大于配置的每轮最大来源数
- **THEN** 通用轮询任务 SHALL 只触发不超过最大来源数的来源
- **AND** 在结果中记录被延后来源数量

#### Scenario: 轮询结果可审计
- **WHEN** 通用轮询任务完成
- **THEN** 系统 SHALL 返回或记录已触发来源、跳过来源、延后来源、失败来源和对应原因

### Requirement: 来源健康必须支持地区化筛选
系统 SHALL 在来源健康视图或等价后台入口中支持按地区查看启用来源、最近抓取结果、长时间未运行、运行中和失败状态。

#### Scenario: 按地区查看来源健康
- **WHEN** 工作人员按中国香港、英国、法国或美国筛选来源健康
- **THEN** 系统 SHALL 只展示该地区来源及其最近抓取摘要

#### Scenario: 地区停滞来源可见
- **WHEN** 某启用国际来源超过停滞阈值没有完成抓取
- **THEN** 来源健康 SHALL 在该来源所属地区下展示长时间未运行或等价停滞状态

#### Scenario: 地区健康查询保持有界
- **WHEN** 工作人员查看来源健康或地区生产概览
- **THEN** 系统 SHALL 使用聚合查询、分页、有限时间窗口或等价方式获取数据
- **AND** 不得为每个地区或每个来源逐条执行无界明细查询
