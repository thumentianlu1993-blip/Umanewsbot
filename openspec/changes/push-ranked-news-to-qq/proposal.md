## Why

QQ 群是强打扰渠道，长期使用 `all_public` 会把普通公开新闻也推到群里；而只按分数阈值判断高价值，又可能偏离用户现在明确的产品口径：本期重点新闻就是 netkeiba 访问量榜和注目数榜命中的新闻。

## What Changes

- 保留 `QQ_PUSH_SCOPE` 作为“全推 / 重点推”的范围配置，并新增重点推送策略配置；本期只实现 `QQ_PUSH_IMPORTANCE_STRATEGY=ranked`。
- 将 QQ 自动推送的重点新闻口径调整为“榜单重点新闻”：`netkeiba:access` 或 `netkeiba:attention`。
- 保留 `QQ_PUSH_SCOPE=all_public` 作为临时调试/灰度配置，但生产推荐回到 `high_value_only`。
- 自动推送只在文章公开发布、无阻断问题、公开 URL 可访问后创建并处理 `QQPushDelivery`；阻断问题复用现有 `NewsArticle.gate_blockers` / `gate_issues.severity=blocker` 口径。
- 已发送过的文章 x 群不重复自动发送，继续复用现有 `QQPushDelivery` 幂等和有限重试机制。
- 继续使用现有消息格式：`【UmaFans】标题`、摘要、`阅读全文：URL`，URL 将由 `use-article-id-public-urls` 子 change 改为 ID URL。

## Capabilities

### New Capabilities
无。

### Modified Capabilities
- `qqbot-auto-push`: 为重点推送增加策略配置，本期使用 `ranked` 策略将重点新闻定义为 netkeiba 访问量榜 / 注目数榜新闻，并补充榜单提升后的已公开文章交付规则。

## Impact

- 代码：`server/stable/services/qq_auto_push.py`，以及发布/自动发布后的入队路径。
- 配置：新增 `QQ_PUSH_IMPORTANCE_STRATEGY=ranked`；生产建议从测试期 `QQ_PUSH_SCOPE=all_public` 切回 `QQ_PUSH_SCOPE=high_value_only`。
- 测试：覆盖榜单来源可推、普通新着不推、未公开不推、有 blocker 不推、重复触发不重复发送。
- 运维：部署后需要在测试群观察自然榜单文章推送，不要求补推历史公开新闻。
