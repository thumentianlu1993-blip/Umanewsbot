# crawl-freshness-and-source-health Specification

## Purpose
TBD - created by archiving change fix-crawl-freshness-and-jra-date-parse. Update Purpose after archive.
## Requirements
### Requirement: JRA 官方新闻日期解析必须兼容无年份格式
系统 SHALL 在抓取 JRA 官方新闻时兼容带年份和无年份的日期文本，不得因 `5月31日` 这类格式导致整个 JRA 抓取任务失败。

#### Scenario: 解析带年份日期
- **WHEN** JRA 新闻列表或详情页日期为 `2026年5月31日`
- **THEN** 系统 SHALL 将日期解析为对应年份、月份和日期

#### Scenario: 解析无年份日期
- **WHEN** JRA 新闻列表或详情页日期为 `5月31日`
- **THEN** 系统 SHALL 优先使用列表月份、URL 或当前东京时间推断合理年份，并继续抓取该新闻

#### Scenario: 跨年附近日期回退
- **WHEN** JRA 新闻日期不含年份，且按当前年份推断出的日期晚于当前东京日期超过 7 天
- **THEN** 系统 SHALL 将该日期回退到上一年

#### Scenario: 单条日期异常不影响同源后续新闻
- **WHEN** JRA 日期解析遇到无法识别的异常格式
- **THEN** 系统 SHALL 记录失败原因，并继续处理同一 JRA 列表中其他可解析新闻

#### Scenario: JRA 整体失败不影响其他来源
- **WHEN** JRA 列表结构整体不可解析或网络请求失败
- **THEN** 系统 SHALL 将 JRA 抓取记录为失败，并且不得影响 netkeiba 新着顺、访问量榜或注目数榜任务执行

### Requirement: netkeiba 榜单抓取必须降低短时热点遗漏概率
系统 SHALL 以高于每 12 小时一次的频率抓取 netkeiba 访问量榜和注目数榜，并保持访问量榜与注目数榜执行时间错开。

#### Scenario: 访问量榜按小时级频率运行
- **WHEN** Celery Beat 加载生产调度
- **THEN** netkeiba 访问量榜 SHALL 至少每小时触发一次抓取任务

#### Scenario: 注目数榜按小时级频率运行
- **WHEN** Celery Beat 加载生产调度
- **THEN** netkeiba 注目数榜 SHALL 至少每小时触发一次抓取任务

#### Scenario: 榜单任务错峰执行
- **WHEN** 访问量榜和注目数榜在同一小时内触发
- **THEN** 两个任务 SHALL 错开执行时间，避免同一时刻集中请求上游

#### Scenario: 来源定义与调度频率一致
- **WHEN** 内置来源同步到 `NewsSource`
- **THEN** netkeiba 访问量榜和注目数榜的 `crawl_interval_minutes` SHALL 与 Celery Beat 中的实际抓取间隔一致

### Requirement: 来源健康必须展示最近抓取结果
系统 SHALL 在后台来源管理或仪表盘中展示每个启用来源的最近抓取结果，使工作人员无需进入服务器日志即可判断来源是否正常。

#### Scenario: 显示最近成功抓取摘要
- **WHEN** 来源最近一次抓取成功且新增为 0
- **THEN** 后台 SHALL 展示最近抓取时间、成功状态、新增数量、重复数量和“无新增”的可理解摘要

#### Scenario: 显示最近失败原因
- **WHEN** 来源最近一次抓取失败
- **THEN** 后台 SHALL 展示最近抓取时间、失败状态和错误摘要

#### Scenario: 区分无新增与抓取失败
- **WHEN** 来源抓取成功但 `new_count=0`
- **THEN** 系统 SHALL 将该结果视为成功无新增，而不得展示为抓取失败

### Requirement: 抓取任务必须保留可审计执行记录
系统 SHALL 为内置抓取任务保留可审计执行记录，包括来源、开始时间、结束时间、状态、新增数、重复数和错误摘要。

#### Scenario: netkeiba 新着顺无新增
- **WHEN** netkeiba 新着顺任务运行成功但抓到的文章均已存在
- **THEN** 系统 SHALL 记录 `success_count=0`、重复数量和成功状态

#### Scenario: JRA 抓取失败
- **WHEN** JRA 抓取任务因来源格式异常失败
- **THEN** 系统 SHALL 记录失败状态和错误摘要，并更新该来源最近抓取状态

#### Scenario: 来源长时间未运行
- **WHEN** 启用来源超过配置阈值没有新的抓取执行记录
- **THEN** 系统 SHALL 能在后台或异常检测中识别该来源为疑似停滞

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

### Requirement: netkeiba 榜单命中必须提升新着来源文章
系统 SHALL 在同一 netkeiba 文章先由新着顺入库、后续又被访问量榜或注目数榜命中时，将文章主来源从 `netkeiba:latest` 提升为对应榜单来源，同时继续记录榜单快照。

#### Scenario: 新着顺文章被访问量榜命中
- **WHEN** 已存在文章的 `source_site=netkeiba`、`source_mode=latest`，且同一 `source_article_id` 被 `source_mode=access` 的抓取 draft 命中
- **THEN** 系统 SHALL 将该文章的 `source_mode` 更新为 `access`
- **AND** 系统 SHALL 创建一条 `source_mode=access` 的 `NewsSnapshot`

#### Scenario: 新着顺文章被注目数榜命中
- **WHEN** 已存在文章的 `source_site=netkeiba`、`source_mode=latest`，且同一 `source_article_id` 被 `source_mode=attention` 的抓取 draft 命中
- **THEN** 系统 SHALL 将该文章的 `source_mode` 更新为 `attention`
- **AND** 系统 SHALL 创建一条 `source_mode=attention` 的 `NewsSnapshot`

#### Scenario: 访问量榜不被注目数榜覆盖
- **WHEN** 已存在文章的 `source_site=netkeiba`、`source_mode=access`，且同一 `source_article_id` 被 `source_mode=attention` 的抓取 draft 命中
- **THEN** 系统 SHALL 保持该文章的 `source_mode=access`
- **AND** 系统 SHALL 仍创建一条 `source_mode=attention` 的 `NewsSnapshot`

#### Scenario: 注目数榜不被访问量榜覆盖
- **WHEN** 已存在文章的 `source_site=netkeiba`、`source_mode=attention`，且同一 `source_article_id` 被 `source_mode=access` 的抓取 draft 命中
- **THEN** 系统 SHALL 保持该文章的 `source_mode=attention`
- **AND** 系统 SHALL 仍创建一条 `source_mode=access` 的 `NewsSnapshot`

#### Scenario: 新着顺不覆盖榜单来源
- **WHEN** 已存在文章的 `source_site=netkeiba`、`source_mode=access` 或 `source_mode=attention`，且同一 `source_article_id` 再次被 `source_mode=latest` 的抓取 draft 命中
- **THEN** 系统 SHALL 保持该文章当前榜单 `source_mode`
- **AND** 系统 SHALL 仍创建一条 `source_mode=latest` 的 `NewsSnapshot`

#### Scenario: 来源配置同步更新
- **WHEN** 系统将文章主来源从 `latest` 提升为 `access` 或 `attention`
- **THEN** 系统 SHALL 同步更新该文章的 `source_config` 和 `source_note`，使后台展示与主来源一致

#### Scenario: 来源提升结果可被后续流程检测
- **WHEN** 系统在一次入库更新中将文章主来源从 `latest` 提升为 `access` 或 `attention`
- **THEN** 入库结果 SHALL 暴露本轮发生来源提升的稳定信号，使后续流程可以判断该文章刚刚成为榜单重点新闻

