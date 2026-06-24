## Why

生产候选新闻池在 `2026-06-23 21:00` 后连续多轮没有新增文章，虽然 netkeiba 新着顺任务实际仍在运行，但后台缺少足够直观的来源健康解释，工作人员只能进入服务器查询 `CrawlJob` 和任务日志判断原因。

同时，JRA 官方新闻抓取已因 `5月31日` 这类无年份日期格式持续失败；netkeiba 访问量榜和注目数榜当前每 12 小时只抓一次，可能错过短时间上榜又掉榜的新闻。

## What Changes

- 修复 JRA 官方新闻日期解析，兼容无年份日期文本，并保证失败不会影响其他来源抓取。
- 调整 netkeiba 访问量榜和注目数榜抓取频率，从半天一次改为更适合发现短时热点的频率。
- 同步更新内置来源定义中的抓取间隔与备注，确保后台展示、异常检测和 Celery Beat 调度口径一致。
- 保留 netkeiba 新着顺每小时抓取的基础策略，但明确其“任务正常但上游无新稿”的诊断口径。
- 在后台来源列表或仪表盘中展示来源最近抓取状态，包括最近抓取时间、状态、新增数、重复数和错误摘要。
- 为连续 `new=0`、连续失败和来源长时间未更新提供更清晰的可观测性和测试覆盖。
- 不在本 change 中处理“榜单快照触发高价值重新评分”，该问题单独进入后续 change。
- 不在本 change 中处理“新闻编辑区选区快速加入术语库”或“术语保存后重新应用/重翻译联动”。

## Capabilities

### New Capabilities

- `crawl-freshness-and-source-health`: 定义抓取调度、新鲜度诊断、JRA 日期解析兼容和后台来源健康展示要求。

### Modified Capabilities

- 无。

## Impact

- `server/app/settings.py`：调整 Celery beat 中访问量榜、注目数榜调度频率。
- `server/stable/services/sources.py`：同步内置来源的 `crawl_interval_minutes` 和来源备注，避免后台显示与实际调度不一致。
- `server/stable/adapters/jra.py`：增强 JRA 日期解析。
- `server/stable/tasks.py`：必要时增强抓取任务日志、`CrawlJob` 记录或来源状态更新。
- `server/stable/views.py` 与 `server/stable/templates/stable/console/`：在来源列表或仪表盘展示抓取健康摘要。
- `server/stable/tests.py`：增加 JRA 日期解析、榜单调度配置、抓取健康展示和连续无新稿诊断相关测试。
- `.env.example` 与 `docs/`：记录新的抓取频率策略、生产排障入口和验收方式。
