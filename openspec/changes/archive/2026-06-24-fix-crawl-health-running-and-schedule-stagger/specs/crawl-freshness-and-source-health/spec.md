## ADDED Requirements

### Requirement: 来源健康必须优先展示运行中抓取
系统 SHALL 在后台来源健康摘要中优先识别最新运行中的 `CrawlJob`。当来源最新抓取记录仍为运行中时，系统不得把该运行中记录的默认计数与旧的 `NewsSource.last_crawl_status` 组合成成功、失败或成功无新增结论。

#### Scenario: 最新任务运行中时显示运行中
- **WHEN** 某来源最新 `CrawlJob.status` 为 `started`，且 `NewsSource.last_crawl_status` 仍保留上一次成功状态
- **THEN** 后台来源健康状态 SHALL 显示为“运行中”，而不得显示为“成功无新增”或“成功”

#### Scenario: 首次任务运行中时不显示长时间未运行
- **WHEN** 某来源没有已完成抓取记录，但存在最新 `CrawlJob.status=started`
- **THEN** 后台来源健康状态 SHALL 显示为“运行中”，而不得显示为“长时间未运行”或“未运行”

#### Scenario: 最近结果使用已完成记录
- **WHEN** 某来源最新 `CrawlJob.status=started`，且上一条已完成抓取记录为成功无新增
- **THEN** 后台 SHALL 将当前状态显示为“运行中”，并且仅把上一条已完成记录作为参考摘要，不得把运行中记录的 `success_count=0` 解释为当前成功无新增

#### Scenario: 陈旧运行中任务显示疑似卡住
- **WHEN** 某来源最新 `CrawlJob.status=started` 且 `started_at` 距今超过 60 分钟
- **THEN** 后台来源健康状态 SHALL 显示为“运行超时”或等价疑似卡住状态，而不得继续显示普通“运行中”

#### Scenario: 长期从未运行来源显示停滞
- **WHEN** 某启用来源没有任何 `CrawlJob`、没有 `last_crawl_at`，且来源创建时间已经超过配置停滞阈值
- **THEN** 后台来源健康状态 SHALL 显示为“长时间未运行”，而不得继续显示普通“未运行”

#### Scenario: 停用来源不显示停滞告警
- **WHEN** 某停用来源没有任何 `CrawlJob`、没有 `last_crawl_at`，且来源创建时间已经超过配置停滞阈值
- **THEN** 后台来源健康状态 SHALL NOT 显示为“长时间未运行”

### Requirement: netkeiba 同源抓取任务必须错峰触发
系统 SHALL 在 Celery Beat 中错峰触发 netkeiba 新着顺、周日高频新着顺、访问量榜和注目数榜，避免同一小时内多个 netkeiba 抓取任务在同一分钟集中请求上游。

#### Scenario: netkeiba 三类任务分钟值互不相同
- **WHEN** Celery Beat 加载抓取调度
- **THEN** `crawl-netkeiba-latest-hourly`、`crawl-netkeiba-access` 和 `crawl-netkeiba-attention` 的触发分钟 SHALL 两两不同

#### Scenario: 访问量榜避开整点新着顺
- **WHEN** Celery Beat 加载抓取调度
- **THEN** `crawl-netkeiba-access` SHALL 不得在每小时 `00` 分触发，并且仍 SHALL 至少每小时触发一次

#### Scenario: 注目数榜与访问量榜保持错峰
- **WHEN** Celery Beat 加载抓取调度
- **THEN** `crawl-netkeiba-attention` SHALL 与 `crawl-netkeiba-access` 错开触发，并且仍 SHALL 至少每小时触发一次

#### Scenario: 榜单任务避开周日高频新着顺
- **WHEN** Celery Beat 加载抓取调度
- **THEN** `crawl-netkeiba-access` 和 `crawl-netkeiba-attention` 的触发分钟 SHALL 避开 `crawl-netkeiba-latest-sunday-rush` 与 `crawl-netkeiba-latest-sunday-rush-end` 的触发分钟

#### Scenario: 生产验收可按固定分钟确认
- **WHEN** 生产部署完成并重启 Celery Beat
- **THEN** 运维人员 SHALL 能在同一小时内观察到 netkeiba 新着顺、访问量榜和注目数榜分别按固定错峰分钟生成 `CrawlJob`

### Requirement: JRA 单篇详情异常不得拖垮整轮抓取
系统 SHALL 在 JRA 官方新闻抓取中区分列表 / 网络级整体失败与单篇详情结构失败。单篇详情页缺少关键节点、标题结构或日期格式异常时，系统必须跳过该篇并继续处理同轮其他可解析新闻；列表抓取、网络请求或数据库写入异常仍可使 JRA 抓取任务整体失败。

#### Scenario: 单篇详情结构异常后继续处理后续新闻
- **WHEN** JRA 同一抓取轮次中第一篇详情页缺少关键日期节点，第二篇详情页结构正常
- **THEN** 系统 SHALL 跳过第一篇、记录跳过摘要，并继续处理第二篇

#### Scenario: JRA 详情结构异常写入抓取摘要
- **WHEN** JRA 抓取跳过一篇详情结构异常新闻
- **THEN** 本轮 `CrawlJob` 和 `NewsSource.last_crawl_message` SHALL 包含跳过数量或首个跳过原因摘要
