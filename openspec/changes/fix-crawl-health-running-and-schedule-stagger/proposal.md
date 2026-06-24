## Why

`fix-crawl-freshness-and-jra-date-parse` 的代码审查发现两个 P2 缺陷：后台来源健康摘要在有运行中 `CrawlJob` 时可能把旧成功状态误展示为“成功无新增”，并且 netkeiba 新着顺与访问量榜都在整点触发，会让同一上游请求集中。

这两个问题都属于抓取新鲜度 change 的上线前返修；如果不先修正，生产验收会出现后台状态误导和调度压力集中。

## What Changes

- 调整来源健康摘要判定顺序：最新 `CrawlJob(status=started)` 必须优先展示为“运行中”，不得混用旧 `NewsSource.last_crawl_status` 得出成功/失败结论。
- 来源从未完成过抓取但已经有运行中 job 时，后台展示“运行中”而不是“长时间未运行”。
- 运行中 job 超过 60 分钟仍未完成时，后台展示“运行超时”或等价疑似卡住状态，避免陈旧 `started` 记录长期遮住真实停滞。
- 启用来源长期没有任何完成记录或运行中记录时，后台也应展示“长时间未运行”，不得长期显示为普通“未运行”。
- 停用来源不得触发“长时间未运行”误报，避免人工关闭的来源继续污染健康告警。
- 对“最近结果”计数只使用已完成的最近抓取记录；运行中 job 的 `success_count=0` 不得被解释为“成功无新增”。
- JRA 单篇详情页结构异常应跳过该篇并记录摘要，不能拖垮同一轮 JRA 抓取；跳过摘要必须能在本轮 `CrawlJob` 和来源最近摘要中追溯，网络或列表级异常仍按整体失败处理。
- 调整 netkeiba 访问量榜 Celery Beat 触发时间，使新着顺、访问量榜、注目数榜在同一小时内错峰运行。
- 错峰分钟必须避开新着顺每小时任务和周日重赏高频补抓分钟；默认采用新着顺 `00` 分、访问量榜 `16` 分、注目数榜 `26` 分。
- 同步更新配置断言、后台来源健康测试和部署文档，明确新的错峰时间与运行中状态语义。
- 不改变抓取频率目标：访问量榜和注目数榜仍保持小时级抓取。
- 不新增数据库模型或迁移。

## Capabilities

### New Capabilities
- `crawl-freshness-and-source-health`: 补充抓取健康能力的运行中状态判定和 netkeiba 同源任务错峰要求，作为 `fix-crawl-freshness-and-jra-date-parse` 的审查返修。

### Modified Capabilities
- 无正式已归档能力被修改；本 change 修正尚未归档的抓取新鲜度能力实现方案。

## Impact

- `server/app/settings.py`：调整 `crawl-netkeiba-access` / `crawl-netkeiba-attention` 的 Celery Beat 分钟配置，避免和新着顺每小时任务及周日重赏高频补抓同时触发。
- `server/stable/views.py`：调整 `_source_health()`，显式处理运行中 job，并避免把运行中计数当作最近成功结果。
- `server/stable/tasks.py`：调整 JRA 单篇详情解析异常处理范围，记录跳过摘要并继续处理后续条目。
- `server/stable/templates/stable/console/`：如需要，展示“运行中”状态 badge。
- `server/stable/tests.py`：新增调度错峰断言，以及运行中 job 不被误判为“成功无新增”或“长时间未运行”的回归测试。
- `docs/current_state.md` 与 `docs/deploy_runbook.md`：更新上线前返修结论、错峰时间和验收入口。
