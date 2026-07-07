## Why

法国 `tdn_france_broad` 来源使用 TDN WordPress search API 后，搜索结果混入 2020/2022/2023/2024 历史文章，且 search item 不带发布时间，现有 adapter 将缺失日期兜底为当前时间，导致旧文被误判为今日新闻并有 5 篇自动发布。该来源已在生产临时暂停，需要在重新启用前修复真实发布时间解析、新鲜度过滤和受影响已发布内容清理流程。

## What Changes

- 修复 `tdn_france_broad`：从 search item 的 `id` 或 `_links.self` 二次读取 TDN post API，使用真实 `date_gmt/date` 作为文章发布时间。
- 禁止 TDN search item 在缺少真实发布时间时兜底为 `timezone.now()`；无法取得真实发布时间的条目必须跳过并记录原因。
- 对 TDN 法国宽关键词来源增加生产新鲜度过滤，丢弃明显超过允许窗口的历史旧文，避免旧文进入翻译、门禁、发布和 QQ 推送链路。
- 补充单元测试和回归测试，覆盖历史 search 结果、无日期 search item、post API 日期解析、详情解析失败跳过和来源统计。
- 上线后清理已误发布的历史旧文，并在验证通过后重新启用 `NewsSource#21`。

## Capabilities

### New Capabilities

- 无

### Modified Capabilities

- `international-racing-coverage`: 法国 TDN 关键词新闻源必须使用真实 post 发布时间，并过滤搜索接口返回的历史旧文。
- `crawl-freshness-and-source-health`: 抓取 adapter 在缺少可信发布时间时不得把文章标记为当前时间，必须跳过或显式记录不可用日期。

## Impact

- 代码：`server/stable/adapters/` 中 TDN / TDN France 相关 adapter、国际新闻抓取流程、探测命令与测试。
- 数据：无新增迁移；需对生产中受影响的已发布历史旧文执行受控清理。
- 运维：部署后需重新启用 `NewsSource#21`，并通过只读探测、真实抓取、健康检查和最近窗口审计验收。
- 风险：上游 TDN search API 仍可能返回历史相关性结果；修复后历史结果应被过滤，不再进入生产文章链路。
