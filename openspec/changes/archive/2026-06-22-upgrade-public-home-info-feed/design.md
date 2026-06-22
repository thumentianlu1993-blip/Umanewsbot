## Context

当前公开站点是第一阶段最低可用前台：`/` 由 `public_news_feed` 读取已发布文章并渲染 `stable/public/feed.html`，`/news/<slug>/` 渲染 `stable/public/detail.html`。首页只按 `published_to_web_at` 倒序分页，模板直接引用后台样式 `stable/console.css`，移动端只是网格卡片变单列。

自动化内容运营上线后，前台将持续出现更多自动发布稿。公开首页不再只是验证“能发布出来”，而要承担真实资讯消费：移动端快速扫读，Web 端利用宽屏展示重点、普通流和辅助信息。用户参考懂球帝的不是足球业务，而是信息层级：重点内容突出，普通内容密度更高。

现有数据已经足够支撑第一版首页信息层级：

- `NewsArticle.effective_title`、`effective_summary`、`cover_image_url`、`tags_json`、`source_note`、`content_category` 可用于新闻卡展示。
- `score_total`、`decision_reason.signals.race_priority`、`race_grade` 可用于头条候选和赛事重点提示。
- `NewsSnapshot.rank`、`comment_count`、`attention_count` 可作为 netkeiba 上游访问/注目热度代理，但不能包装成本站浏览量或本站评论。

现有数据不足以支撑站内社区、站内热门、手工置顶、专题和赛事日历，因此这些能力必须从本轮主 change 中剥离。

## Goals / Non-Goals

**Goals:**

- 建立公开站点首页的主信息架构，作为后续前台子任务的指导规范。
- 在同一公开 URL 下同时支持桌面 Web 与移动 H5，不新增移动端专用路由。
- 将首页从说明型大卡片网格升级为资讯型信息流：
  - 移动 H5：轻顶部、轻量头条、高密度左文右图新闻列表。
  - 桌面 Web：轻导航、主头条、普通新闻流、右侧热门/重点模块。
- 保持普通新闻流按发布时间倒序，避免旧高分稿长期压过新稿。
- 基于现有字段选择头条和热门代理，不新增数据库模型。
- 为公开站点建立独立样式入口和可复用模板片段，减少与后台样式耦合。
- 统一文章详情页公开站点视觉和移动阅读体验。
- 采用严格 TDD：每个可测试行为单独执行 RED -> GREEN -> REFACTOR，先写一个失败测试并确认红，再写最小实现使其变绿，再重构；视觉布局用浏览器视口验收作为 CSS 层补充。

**Non-Goals:**

- 不做原生 App。
- 不引入独立前端构建系统、SPA 或新 JavaScript 框架。
- 不新增手工置顶、推荐位、专题、搜索频道、赛事日历或站内评论模型。
- 不采集新的外部数据源，不改抓取、翻译、AI 改写、自动发布或 QQ 推送链路。
- 不在本轮引入站内浏览量统计；热门模块只能使用上游热度代理或评分回退。
- 不改变公开 URL、后台入口或生产部署架构。

## Decisions

### 保持单 URL 响应式，而不是拆移动端路由

公开首页继续使用 `/`，文章详情继续使用 `/news/<slug>/`。模板和 CSS 根据视口展示不同布局：移动端优先信息流，桌面端使用宽屏门户结构。

备选方案：

- 增加 `/m/` 或单独 H5 路由：短期实现直观，但会造成 SEO、分享链接、测试和模板维护重复。
- 只做 CSS 缩放现有大卡片：改动最小，但无法解决信息密度和单卡高度失控问题。

### 新增公开站点模板基础设施

新增公开站点 base template，并拆出头条、新闻卡、热门列表、分页、详情页顶部等模板片段。`feed.html` 只负责编排页面结构，不再承载所有 HTML。

建议结构：

```text
server/stable/templates/stable/public/
  base.html
  feed.html
  detail.html
  _article_card.html
  _headline.html
  _hot_list.html
  _pagination.html
```

这样后续 `add-public-topic-search-navigation` 或 `add-race-calendar-sidebar` 可以复用基础框架，而不是继续复制完整页面。

### 新增独立 `public.css`

公开站点使用独立 `server/stable/static/stable/public.css`。后台继续使用 `console.css`，公开页面不再依赖后台 `.btn`、`.badge`、`.panel`、`.article-title` 等共享类。

备选方案：

- 继续把样式写进 `console.css`：文件已超过 1000 行且承载后台响应式规则，继续叠加会提高后台回归风险。
- 引入 Tailwind 或前端构建：当前项目没有前端构建系统，为首页改版引入会违背“先闭环可用”的阶段原则。

### 首页数据分层使用现有字段

实现时建议把首页上下文构建为清晰结构：

```text
published_articles
  ├─ headline_article
  ├─ latest_articles
  ├─ hot_articles
  └─ feed_meta / category labels
```

头条选择规则：

- 基础范围：`workflow_status=PUBLISHED` 且有 `published_to_web_at`。
- 优先近 72 小时文章；数量不足时回退到近 7 天；再不足时回退到最新已发布文章。
- 排序信号：`race_priority` P0/P1、`score_total`、是否有封面、`published_to_web_at`。
- UI 不应把命中马名直接称为“P0 马”，因为现有 `p0_horse_hits()` 实际是所有正式马名命中按优先级排序。

普通新闻流：

- 保持 `published_to_web_at desc, id desc`。
- 首屏可排除头条文章，避免重复；分页行为必须稳定。
- 移动端卡片高度通过标题行数、图片比例、元信息行数控制。

热门代理：

- 优先读取每篇文章最近的 `NewsSnapshot`，`source_mode=access` 的小 `rank` 权重最高，`attention` 次之。
- `comment_count` 和 `attention_count` 只作为上游热度信号，不显示为本站评论。
- 没有快照时用 `score_total + recency` 作为回退，不显示具体热度数字。
- 只在有限候选集内组装热门代理，例如近 7 天或最新 48 篇已发布文章，再取前 6 条展示。
- 实现不得对首页候选文章逐篇查询快照；应使用批量 `NewsSnapshot` 查询、`Prefetch` 或等价方式避免 N+1。

### 不在本轮增加首页运营模型

手工置顶/推荐位会引入新模型、后台表单、过期时间、冲突处理和生产运营规则。它应该是后续 `add-homepage-editorial-placement`，而不是混进主首页改版。

主 change 应先验证算法化首页是否足够支撑资讯消费；当运营需要“指定头条”成为真实痛点，再新增类似 `HomepagePlacement` 的模型：

```text
article, slot, position, is_active, starts_at, ends_at, note, created_by
```

### 页面文案克制，避免把功能说明放进页面

首页不再使用大段“这里展示后台已审核发布的新闻稿”式说明。顶部只承担品牌、导航和轻量状态表达；内容本身成为首屏主体。

### 严格 TDD 执行顺序

本 change 实施时必须按行为逐轮执行 RED -> GREEN -> REFACTOR。每轮只新增当前行为需要的失败测试，确认测试在当前实现下失败后，才写对应最小实现，并在变绿后做必要重构。不得一次性批量写完全部测试后再开始实现。

需要覆盖的行为包括：

- 发布过滤：未发布文章不出现在公开首页。
- 头条选择：近期高价值、有封面文章优先，低量内容有回退。
- 普通新闻流：发布时间倒序、分页稳定、首屏不重复头条。
- 热门代理：优先使用上游快照，无快照时评分和时间回退，并避免无上限扫描或 N+1 快照查询。
- 详情页：继续使用有效稿件字段并展示来源、原文链接和时间。
- 静态资源：公开页面引用 `public.css`，不再以 `console.css` 作为主要样式入口。

每个新增测试在当前 MVP 首页实现下应先失败。只有在确认当前行为的测试失败后，才能进入该行为对应的视图、模板或 CSS 最小实现。CSS 的视觉细节无法完全依赖单元测试，因此在单元测试通过后，必须补充浏览器桌面/移动视口验收。

备选方案：

- 先实现再补测试：速度更快，但容易把现有大卡片页面“修修补补”成另一个不可维护状态。
- 只做浏览器验收：能看出视觉问题，但无法保护头条选择、排序、发布过滤和静态资源解耦等行为。

## Risks / Trade-offs

- [头条算法选择不符合人工预期] -> 本轮使用保守可解释排序；手工置顶作为二期独立 change。
- [上游热度被误解为本站评论] -> UI 文案使用“原站关注”“上游热度”或不显示数字，禁止写成本站评论。
- [缺图文章影响卡片质量] -> 卡片需要无图状态；头条优先有封面文章，普通流允许无图但布局仍稳定。
- [公开样式解耦造成一次性改动较多] -> 保持后台 `console.css` 不动或少动，公开页只引用 `public.css`。
- [移动端中文标题过长撑高卡片] -> 使用固定图片比例、标题行数限制和稳定元信息行，浏览器验收覆盖窄屏。
- [热门查询引发复杂 ORM] -> 首版可在有限候选集内用 Python 组装最近快照，避免为展示引入复杂持久化或缓存。
- [旧浏览器 CSS 支持差异] -> 使用基础 CSS Grid/Flex 和渐进增强，不依赖复杂运行时脚本。
- [TDD 增加前期耗时] -> 只把可自动化保护的行为写入 Django 测试；纯视觉细节留给浏览器验收，避免测试过度脆弱。

## Migration Plan

1. 逐行为执行 TDD 循环：发布过滤与普通流、头条选择与回退、热门代理、公开静态资源、详情页有效字段。
2. 每轮先写一个失败测试并记录 RED，再写最小实现使其 GREEN，随后做局部 REFACTOR 并保持测试通过。
3. 创建公开站点 base template、模板片段和 `public.css`。
4. 重构 `public_news_feed` 的上下文组装，提供头条、普通流、热门代理和轻量展示信号。
5. 调整 `feed.html` 为 Web/H5 响应式信息流布局。
6. 调整 `detail.html` 复用公开站点基础样式。
7. 运行新增测试并确认全部通过。
8. 本地执行 `DB_ENGINE=sqlite python manage.py check`。
9. 本地执行 `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable`。
10. 启动本地开发服务器，使用浏览器验收桌面和移动视口。
11. 更新 `docs/current_state.md` 和 `docs/project_status.md`，记录 OpenSpec 主 change 与后续子 change 边界。

回滚策略：本轮不涉及迁移和生产配置。若页面改版出现问题，回滚公开模板、`public.css` 和 `public_news_feed` 上下文即可恢复旧首页；后台样式和数据链路不应受影响。

## Follow-up Change Map

- `add-homepage-editorial-placement`：手工头条、推荐位、置顶、运营排序。
- `add-public-topic-search-navigation`：搜索入口、标签页、频道页、专题页。
- `add-race-calendar-sidebar`：结构化赛事日历、今日重要赛事、赛程侧栏。
- `add-public-engagement-metrics`：站内浏览量、分享量、评论或其他真实站内热度。

这些 change 必须以本 change 建立的公开站点模板、样式和首页数据分层为基础继续扩展。

## Open Questions

- 站点品牌展示使用 `UmaFans`、`赛马新闻` 还是中文正式名，实施前可按现有域名和页面语境先保守处理。
- 第一版是否展示搜索样式入口：如果没有真实搜索页，建议不展示不可用搜索框。
- 右侧热门模块是否显示上游评论数字：建议首版只显示排行和来源/时间，避免用户误解为本站评论。
