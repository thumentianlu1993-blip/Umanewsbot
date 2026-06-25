# 榜单重点新闻 QQ 推送总纲

## 背景

QQ 群自动推送已经具备多群、去重、有限重试、URL 检查、OneBot 业务失败识别和按群限速能力。测试期曾使用 `QQ_PUSH_SCOPE=all_public` 验证链路，但长期全推会刷屏，也不符合当前“重点新闻优先”的运营目标。

本轮目标是把 QQ 自动推送收敛到 netkeiba 访问量榜和注目数榜命中的新闻，同时把文章公开 URL 从标题 slug 改为全局唯一文章 ID，改善 QQ 消息中的链接可读性。

## 总体原则

- 主体能力由三个 OpenSpec 子 change 承载；本文档只作为本轮协调总纲，不作为产品能力规格归档。
- 本期 QQ 重点推送统一采用“按榜单推”：`netkeiba:access` 与 `netkeiba:attention`。
- 后续可能扩展多种推送方式，例如“按榜单推 + 每场比赛当天高频推”和“按分数推”，因此实现时需要把“是否全推”和“重点如何判定”分开配置。
- QQ 推送不得绕过发布门禁；blocker 判断复用现有 `NewsArticle.gate_blockers` / `gate_issues.severity=blocker` 结构化结果。
- 不补推历史公开新闻，以上线后的自然抓取、翻译、发布和榜单提升触发为准。
- 本轮全部实现并部署验收后，应提醒维护者尽可能归档已经完成的 OpenSpec change，避免 active change 长期堆积。

## 子 change 拆分

1. `elevate-ranked-netkeiba-sources`
   - 负责来源覆盖规则。
   - `netkeiba:access` 与 `netkeiba:attention` 可以覆盖 `netkeiba:latest`。
   - `netkeiba:access` 与 `netkeiba:attention` 之间不互相覆盖。
   - 入库结果必须暴露 `source_elevated` 或等价稳定信号，供已公开文章后续进入 QQ 推送编排。

2. `push-ranked-news-to-qq`
   - 负责 QQ 自动推送策略返修。
   - `QQ_PUSH_SCOPE` 继续表示推送范围：`high_value_only` 只推重点，`all_public` 临时全推公开文章。
   - 新增 `QQ_PUSH_IMPORTANCE_STRATEGY=ranked`，本期只支持榜单策略。
   - 榜单策略下，仅 `source_site=netkeiba` 且 `source_mode=access` 或 `attention` 的公开文章可进入自动推送。
   - 文章必须已公开、无 blocker、公开 URL 可访问；已发送的文章 x 群依靠 `QQPushDelivery` 唯一约束避免重复发送。

3. `use-article-id-public-urls`
   - 负责公开文章 URL 改造。
   - 文章详情主 URL 改为 `/news/<article_id>/`。
   - 非纯数字旧 slug URL 保持兼容跳转到 ID URL。
   - 纯数字旧 slug 概率极低，本轮不单独兼容。
   - QQ 推送消息自然使用新的 `article.public_path` 生成 ID URL。

## 推荐实施顺序

1. 先实现并部署 `elevate-ranked-netkeiba-sources`，观察自然榜单抓取是否正确提升来源。
2. 再实现并部署 `push-ranked-news-to-qq`，将生产配置切到 `QQ_PUSH_SCOPE=high_value_only` 与 `QQ_PUSH_IMPORTANCE_STRATEGY=ranked`。
3. 最后实现并部署 `use-article-id-public-urls`，抽检 `/news/<id>/` 与非纯数字旧 slug 跳转。
4. 本轮需求完成后，先将已完成的 `add-qqbot-auto-push` 同步或归档为正式 `qqbot-auto-push` 规格，再归档依赖它的 `push-ranked-news-to-qq`。
5. 归档时同步检查其他已完成但仍处于 active 状态的 change，能归档的尽量归档。

## 验收口径

- netkeiba 新着顺文章首次入库后，后续命中访问量榜或注目数榜时，主来源会被提升。
- 已公开文章在榜单提升后可以进入 QQ 自动推送编排。
- `high_value_only + ranked` 下，新着顺普通文章不推，访问量榜和注目数榜文章可推。
- 有 blocker 的文章不推，且 blocker 判断与自动发布门禁使用同一结构化结果。
- QQ 测试群只观察上线后的自然榜单新闻，不要求补推所有已发表新闻。
- 文章详情主链接使用全局唯一文章 ID，QQ 消息中的 `阅读全文` 链接不再包含标题全文。
