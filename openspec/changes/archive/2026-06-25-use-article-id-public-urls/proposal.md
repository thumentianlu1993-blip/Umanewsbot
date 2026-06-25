## Why

当前公开详情页 URL 使用文章标题 slug，日文/中文长标题会让链接非常长，在 QQ 群消息中不易阅读，也不利于复制、转发和后续统计。文章数据库 ID 已经全局唯一，适合作为第一阶段稳定、短链接的公开路径参数。

## What Changes

- 将公开文章详情主路径改为 `/news/<article_id>/`。
- `NewsArticle.public_path`、首页/详情页/后台“前台查看”链接和 QQ 推送 URL 均使用 ID URL。
- 保留旧 `/news/<slug>/` 路由兼容已发链接，查到文章后跳转到对应 ID URL。
- 公开详情页仍只展示 `workflow_status=published` 且 `published_to_web_at` 非空的文章。
- 不删除 `public_slug` 字段，避免破坏旧数据与兼容跳转。

## Capabilities

### New Capabilities
无。

### Modified Capabilities
- `public-home-info-feed`: 公开资讯流和详情页链接从标题 slug 路径切换为文章 ID 路径，并保持旧 slug 兼容。

## Impact

- 代码：`server/stable/models.py`、`server/app/urls.py`、`server/stable/views.py`，以及依赖 `article.public_path` 的模板和 QQ 推送服务。
- 数据：不需要新增字段或迁移，继续保留 `public_slug`。
- 测试：覆盖 `/news/<id>/` 可访问、未发布文章 ID 不可访问、旧 slug URL 跳转、首页和 QQ 消息使用 ID URL。
- 运维：部署后需抽检旧链接跳转和 QQ 消息链接可访问。
