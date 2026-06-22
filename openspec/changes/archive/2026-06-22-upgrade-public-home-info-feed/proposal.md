## Why

当前公开首页仍是第一阶段 MVP 形态：大说明文案、大卡片网格、移动端单列卡片和后台 `console.css` 复用，已经无法承载持续自动发布后的高频资讯消费。用户希望网站同时支持 Web 与移动端 H5，并把首页从“大卡片 Demo 感”升级为成熟资讯流：重点内容突出，普通新闻高密度、标题和图片清晰，移动端阅读效率接近懂球帝式信息流体验。

本 change 作为公开站点首页升级的主指导规范，先定义可闭环的首页与详情页体验边界；后续手工置顶、搜索频道、专题、赛事日历等子能力应基于本 change 的布局、数据分层和验收标准继续扩展。

## What Changes

- 将公开站点首页升级为 Web + 移动 H5 共用数据源、不同布局策略的信息流：
  - Web 端采用资讯门户结构：轻导航、重点头条、普通新闻流、右侧热门/重点模块。
  - 移动 H5 采用高效信息流结构：轻顶部、轻量头条区、高密度左文右图新闻列表。
- 重构公开首页数据上下文，基于现有已发布文章数据提供：
  - `headline_article`：用于首屏重点头条。
  - `latest_articles`：保持发布时间倒序的普通新闻流。
  - `hot_articles`：基于上游访问/注目快照或自动评分的热门代理列表。
  - `featured_signals`：用于展示赛事等级、内容类型、标签、来源和时间等轻量元信息。
- 复用现有 `NewsArticle` 与 `NewsSnapshot` 字段，不在本轮新增首页运营模型：
  - 标题、摘要、正文：`effective_title` / `effective_summary` / `effective_body`
  - 图片：`cover_image_url`
  - 标签与分类：`tags_json` / `content_category`
  - 内容价值：`score_total` / `decision_reason.signals.race_priority`
  - 上游热度代理：`NewsSnapshot.rank` / `comment_count` / `attention_count`
- 从后台样式中解耦公开站点样式，新增独立公开站点 CSS 与模板基础结构，避免继续把前台规则堆入 `console.css`。
- 统一文章详情页公开站点视觉，使详情页与首页共享公开站点基础样式、顶部导航、内容排版和移动端阅读体验。
- 保持现有公开 URL 不变：
  - `/` 仍为公开首页。
  - `/news/<slug>/` 仍为文章详情页。
- 保持发布过滤规则不变：公开页面只能展示 `workflow_status=PUBLISHED` 的文章。
- 实施阶段采用严格 TDD：
  - 每个可测试行为单独执行 RED -> GREEN -> REFACTOR：先写一个失败测试并确认红，再写最小实现使其变绿，再重构。
  - 禁止一次性批量写完全部测试后再进入实现；纯视觉 CSS 细节用浏览器验收补足。
  - 视觉布局通过移动/桌面浏览器视口验收补足，作为 CSS 与响应式体验的验收层。
- 明确本轮非目标：
  - 不做原生 App。
  - 不做个性化推荐、无限滚动、站内浏览量、站内评论或用户系统。
  - 不做手工置顶/推荐位模型。
  - 不做搜索页、频道页、专题页。
  - 不做结构化赛事日历或赛程数据建模。
  - 不改抓取、翻译、AI 改写、自动发布、QQ 推送或 Docker Compose 主架构。

## Capabilities

### New Capabilities

- `public-home-info-feed`: 公开站点首页和文章详情页的信息层级、响应式 Web/H5 布局、头条/普通流/热门代理数据分层与验收标准。

### Modified Capabilities

- 无。

## Impact

- 影响 `server/stable/views.py` 中公开首页上下文组装和文章详情渲染。
- 影响 `server/stable/templates/stable/public/` 下公开首页、详情页和新增模板片段。
- 影响 `server/stable/static/stable/` 下公开站点样式文件；后台样式应尽量保持稳定。
- 影响 `server/stable/tests.py` 中公开页面相关测试，需按严格 TDD 循环逐个补充会失败的头条选择、普通流排序、热门代理、发布过滤、静态资源和详情页展示测试，再写对应最小实现。
- 需要更新 `docs/current_state.md` 与 `docs/project_status.md`，记录公开首页升级进入 OpenSpec 主 change 阶段。
- 不需要新增数据库迁移，不需要新增外部依赖，不涉及生产部署或服务器运行态变更。
