## Why

当前 `NewsSnapshot` 会记录访问量榜和注目数榜命中，但文章主记录仍可能停留在首次抓到时的 `netkeiba:latest`。这会让后续自动化和 QQ 推送无法稳定识别“后来被榜单命中的重点新闻”。

## What Changes

- 当同一 netkeiba 新闻先由新着顺入库，后续又被访问量榜或注目数榜命中时，将 `NewsArticle.source_mode` 从 `latest` 提升为对应榜单来源。
- 同步更新文章的 `source_config`、`source_note` 和最近抓取 job，使后台、自动化和排查视图看到一致的主来源。
- 来源提升结果必须对后续流程可检测，使 QQ 推送子 change 能识别“已公开文章刚刚变成榜单重点新闻”。
- 保留每次榜单命中的 `NewsSnapshot`，继续作为热度证据和首页热门代理数据。
- 明确不允许 `access` 与 `attention` 互相覆盖，避免榜单之间来回抖动。
- 明确 `latest` 不能覆盖已经被榜单提升的文章。

## Capabilities

### New Capabilities
无。

### Modified Capabilities
- `crawl-freshness-and-source-health`: 榜单抓取不仅写入快照，还会在受控条件下更新文章主来源。

## Impact

- 代码：`server/stable/services/ingestion.py`，必要时补充来源辅助函数。
- 数据：不要求新增数据库字段或迁移，复用 `NewsArticle.source_mode/source_config/source_note/crawl_job` 与 `NewsSnapshot`。
- 测试：新增入库重复文章的来源提升与不覆盖规则测试。
- 后续依赖：`push-ranked-news-to-qq` 将依赖本 change 提供的主来源提升结果。
