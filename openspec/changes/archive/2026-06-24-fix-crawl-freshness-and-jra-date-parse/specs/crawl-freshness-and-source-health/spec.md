## ADDED Requirements

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
