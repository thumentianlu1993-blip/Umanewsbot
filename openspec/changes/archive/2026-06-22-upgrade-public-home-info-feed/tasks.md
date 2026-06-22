## 1. 严格 TDD 执行护栏

- [x] 1.1 (application) 确认本 change 的可测试行为按 RED -> GREEN -> REFACTOR 单独推进；不得一次性批量写完全部测试后再实现。
- [x] 1.2 (application) 为公开页面测试准备最小 fixture/helper，只服务测试数据构造；随后从第一个 RED 测试开始。

## 2. 发布过滤与普通新闻流 TDD 循环

- [x] 2.1 (application) [RED] 新增公开首页数据层测试，断言 `/` 只在 `latest_articles` 中展示已发布文章，并按 `published_to_web_at desc, id desc` 排序；确认当前实现失败。
- [x] 2.2 (application) [GREEN] 最小化重构 `public_news_feed` 查询和上下文，提供 `latest_articles` 并保持发布过滤与排序。
- [x] 2.3 (application) [REFACTOR] 清理公开首页查询 helper 或上下文命名，重跑 2.1 测试保持通过。

## 3. 头条选择 TDD 循环

- [x] 3.1 (application) [RED] 新增头条选择测试，覆盖近 72 小时高赛事优先级、高分且有封面的已发布文章应成为 `headline_article`；确认当前实现失败。
- [x] 3.2 (application) [GREEN] 最小实现 `headline_article` 选择逻辑，按近期范围、赛事优先级、自动评分、封面和发布时间排序。
- [x] 3.3 (application) [RED] 新增低量内容回退测试，覆盖近 72 小时无候选时回退到近 7 天或最新已发布文章；确认当前实现失败。
- [x] 3.4 (application) [GREEN] 最小实现头条回退逻辑，并确保首屏普通流不重复头条。
- [x] 3.5 (application) [REFACTOR] 提炼头条排序信号，避免在模板中写业务排序逻辑，重跑第 3 组测试保持通过。

## 4. 热门代理 TDD 循环

- [x] 4.1 (application) [RED] 新增热门代理测试，覆盖 `NewsSnapshot` 上游访问/注目快照优先于无快照文章；确认当前实现失败。
- [x] 4.2 (application) [GREEN] 最小实现 `hot_articles`，在有限已发布候选集内批量读取快照并生成热门代理列表。
- [x] 4.3 (application) [RED] 新增热门代理回退测试，覆盖无快照时按自动评分和发布时间回退；确认当前实现失败。
- [x] 4.4 (application) [GREEN] 最小实现无快照回退，并确保页面不把上游 `comment_count` 或 `attention_count` 标注为本站评论/浏览量。
- [x] 4.5 (application) [REFACTOR] 检查热门代理候选上限和快照读取方式，避免无上限扫描或逐篇文章查询最近快照。

## 5. 公开样式与详情页 TDD 循环

- [x] 5.1 (application) [RED] 新增公开静态资源测试，断言首页和详情页引用 `public.css`，且不再以 `console.css` 作为主要样式入口；确认当前实现失败。
- [x] 5.2 (application) [GREEN] 新增公开站点 base template 和 `server/stable/static/stable/public.css`，最小化接入首页与详情页。
- [x] 5.3 (application) [RED] 新增详情页公开结构测试，覆盖有效标题、摘要、正文、来源、原文链接和发布时间继续展示，并使用公开站点基础结构；确认当前实现失败。
- [x] 5.4 (application) [GREEN] 最小化重写 `stable/public/detail.html`，复用公开站点 base 和公开样式，保留有效稿件字段优先级。
- [x] 5.5 (application) [REFACTOR] 抽出公开页模板片段，包括头条、新闻卡、热门列表、分页和空状态，重跑第 5 组测试保持通过。

## 6. 纯视图布局实现与浏览器验收

- [x] 6.1 (application) [View] 重写 `stable/public/feed.html`，在同一 URL 下编排桌面 Web 门户布局和移动 H5 信息流布局。
- [x] 6.2 (application) [View] 实现桌面 Web 布局：轻导航、主头条、普通新闻流、右侧热门或重点辅助模块。
- [x] 6.3 (application) [View] 实现移动 H5 布局：轻顶部、轻量头条、高密度左文右图新闻列表。
- [x] 6.4 (application) [View] 为普通新闻卡设置稳定的图片比例、标题行数、元信息行和缺图状态，防止移动端卡片高度失控或文字遮挡。
- [x] 6.5 (application) [View] 优化文章详情页移动阅读排版，控制标题、封面、正文和来源信息在窄屏下不互相遮挡。

## 7. 测试通过与本地验证

- [x] 7.1 (application) 运行新增公开页面测试，确认所有 TDD 循环对应测试通过。
- [x] 7.2 (application) 执行 `DB_ENGINE=sqlite python manage.py check`。
- [x] 7.3 (application) 执行 `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable`。
- [x] 7.4 (application) 执行 `openspec validate upgrade-public-home-info-feed --strict` 和 `openspec validate --all`。

## 8. 浏览器验收

- [x] 8.1 (application) 启动本地开发服务器，使用浏览器验收桌面首页、移动首页、桌面详情页和移动详情页。
- [x] 8.2 (application) 在浏览器验收中检查标题、图片、按钮、标签和来源时间不发生遮挡，并确认页面首屏以新闻内容为主。
- [x] 8.3 (application) 在浏览器验收中确认移动端普通新闻卡高度受控，缺图文章不破坏列表布局。
- [x] 8.4 (application) 在浏览器验收中确认桌面端主内容与右侧辅助模块信息层级清晰。

## 9. 文档与收尾

- [x] 9.1 (operations) 更新 `docs/current_state.md`，记录公开首页资讯流升级的实现、严格 TDD 执行和验证状态。
- [x] 9.2 (operations) 更新 `docs/project_status.md`，同步项目级摘要中的前台体验状态。
- [x] 9.3 (operations) 如实施过程中形成新的长期决策，更新 `docs/decisions.md`。
- [x] 9.4 (operations) 确认本轮不涉及生产部署、数据库迁移或部署运行手册变更；若实际触及部署流程，再更新 `docs/deploy_runbook.md`。
