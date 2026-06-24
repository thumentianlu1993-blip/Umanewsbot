# 当前状态

## 当前结论

项目当前已经完成正式域名 HTTP 接入修复，`umafans.run` 与 `www.umafans.run` 已可访问。  
“自动化内容运营 + AI 编辑改写 MVP”已完成代码侧与生产侧上线，当前处于上线后观察与质量抽检阶段。

仓库已于 `2026-06-06` 加入 OpenSpec + Codex 协作支持，用于在较大功能、跨模块改动、架构调整和生产高风险变更前先对齐规格，再进入实现。

OpenSpec change `add-term-candidate-discovery` 已完成实现、自动化测试、本地隔离环境浏览器验收，并归档为 `2026-06-06-add-term-candidate-discovery`；正式能力规格已同步到 `openspec/specs/term-candidate-discovery/spec.md`。

`2026-06-07` 已将术语候选发现部署到生产：服务器从 `7123e4e` 拉到 `e2e3e07`，应用迁移 `0006` 新建候选与证据表，`.env` 补入术语发现开关并保持 `TERM_DISCOVERY_ENABLED=false`（灰度，先关后开）。本次部署同时核实线上 `AUTOMATION_ENABLED=true`、`REWRITE_PROVIDER=siliconflow` 仍在生效。

仓库已明确长期语言约定：Codex 新增或维护的协作文档、OpenSpec 产物与代理说明默认使用中文；仅保留必要的代码标识符、命令和工具机器语法。

`2026-06-19` 已创建公开首页资讯流升级主 OpenSpec change：`upgrade-public-home-info-feed`。该 change 作为后续前台 Web + 移动 H5 首页子任务的指导规范，目标是把当前 MVP 公开首页从“大说明 + 大卡片网格”升级为成熟资讯流：移动端轻头条 + 高密度新闻列表，桌面端门户式主内容 + 侧栏。`2026-06-21` 已完成 plan-eng-review 与 `/opsx:apply` 本地实现；实施过程按严格 TDD 执行发布过滤、头条选择、普通流去重、热门代理、公开静态资源和详情页结构测试，并已通过本地 Django 测试、OpenSpec 校验和桌面/移动浏览器验收。`2026-06-22` 已将 delta spec 同步为正式规格 `openspec/specs/public-home-info-feed/spec.md`，并归档为 `openspec/changes/archive/2026-06-22-upgrade-public-home-info-feed/`；同日 PR #1 已合并并部署到生产，服务器运行 `e834f58`，公开首页已切换到 `stable/public.css` 和新资讯流模板。`2026-06-23` PR #2 已合并并部署生产，服务器运行 `04e2ee9`，移动 H5 首屏密度 follow-up 已上线。

`2026-06-24` 已完成自动发布门禁优化 OpenSpec change：`refine-automation-publish-gates` 的实现、PR 合并与生产上线。代码已将自动发布门禁拆为 `blocker / warning / info`：`blocker` 阻断自动发布，`warning` 初期不阻断但记录并对高价值文章邮件告警，`info` 仅用于诊断；同时支持基准翻译稿自动发布、高价值来源评分放行、非马名普通词过滤、关键术语分层校验和重复内容拦截。生产服务器当前运行 PR #4 squash merge 后的提交 `42a4622`，迁移 `stable.0009_automation_publish_gates` 已应用。

## 已完成内容

- 域名购买与解析
- 正式域名 `umafans.run` / `www.umafans.run` 接入
- 本轮线上问题已修复，正式域名已可访问
- 公网服务器上 `Django + PostgreSQL + Celery + Redis + Docker Compose + Nginx` 主链路已运行
- 基础抓取、翻译、后台、前台链路已具备可继续迭代的基础
- 自动化运营 MVP 代码侧已完成：
  - 翻译成功后可进入自动评分分流
  - 支持 `auto / manual / ignored` 三类分流
  - 支持基准翻译稿与 AI 改写稿双层保存
  - 支持一致性校验、批量自动发布、自动化日志与通知日志
  - 后台候选池、详情页、编辑台、日志页已展示自动化状态与决策留痕
  - 前台展示优先级已调整为人工稿优先，其次改写稿，最后基准翻译稿
- OpenSpec + Codex 工作流已完成仓库级配置：
  - `openspec/config.yaml` 记录真实项目上下文、验证命令和任务域路由
  - `.codex/skills/openspec-*` 提供提案、实现、同步与归档技能
  - `.codex/agents/` 提供 `application / integration / operations` 领域代理与只读安全审查代理
  - `AGENTS.md` 已补充规格驱动开发与子代理使用约定
- 专有术语候选发现与待标注池已完成：
  - 支持马名、比赛名、骑手名和马主名发现
  - 支持候选去重、证据聚合、工作人员审核和安全写入正式术语
  - 已完成 69 项测试与本地浏览器功能验收
  - 生产默认关闭，等待灰度启用

## 本轮问题简述

本轮线上问题并不是单一故障，而是多层运行态与仓库预期不一致叠加导致：

- 早期曾出现 DNS 解析未生效或本地查询返回 `NXDOMAIN`
- 服务器曾运行旧版 `nginx` 配置，仍保留 `80 -> 443` 跳转逻辑
- 服务器 `.env` 曾保留旧版 IP + HTTPS 强制配置
- 服务器运行中的 commit 一度与仓库当前预期不一致
- 最终通过对齐服务器代码版本、运行态配置、域名配置，完成正式域名 HTTP 接入修复

## 当前线上状态

- 线上域名已通
- 正式域名 `umafans.run` / `www.umafans.run` 可访问
- 自动化运营 MVP 已上线
- 公开首页资讯流升级已上线生产：`/` 使用公开站点专用 `public.css`、头条、普通新闻流和原站热度模块；移动 H5 已展示头条 + 高密度左文右图列表；移动端首屏密度 follow-up 已上线，390px 视口首屏可见 4 条普通新闻卡
- 自动化能力通过 `.env` 中 `AUTOMATION_ENABLED` 控制，当前已进入灰度运行与质量观察阶段
- 已核实线上 `AUTOMATION_ENABLED=true`、`AUTO_REWRITE_ENABLED=false`、`AUTO_PUBLISH_CONTENT_SOURCE=base_translation`、`AUTOMATION_WARNING_EMAIL_ENABLED=true`，当前按“基准翻译稿自动发布 + 高价值 warning 邮件告警”灰度运行
- 术语候选发现代码已部署到生产（`e2e3e07`，迁移 `0006` 已应用），`TERM_DISCOVERY_ENABLED=false` 默认关闭，等待单篇抽检后灰度开启
- `2026-06-24` 已完成 QQ Bot / OneBot 生产运行态配置：独立 NapCat 容器 `umanewsbot-onebot-1` 已启动，OneBot HTTP 仅绑定服务器 `127.0.0.1:3000` 并通过 Docker 网络别名 `onebot` 给应用访问，测试群 `1026525240` 已写入 `PushTarget`，OneBot 直连与 Django `BotPusher` 均已成功发送测试消息。

## 下一步优先级

1. 继续观察公开首页资讯流生产运行，重点确认 `/`、`/news/<slug>/`、图片、`public.css`、移动 H5 首屏密度和自动发布内容长期表现
2. 生产迁移已于 `2026-06-07` 完成；下一步在生产做单篇手动重新发现并抽检术语候选质量，确认后灰度启用 `TERM_DISCOVERY_ENABLED`
3. 观察自动化发布质量与 `AutomationLog`
4. 补充翻译 warning 可视化和术语库补全流程
5. QQ Bot 自动推送合入、部署并灰度开启测试群推送
6. HTTPS / 证书接入
7. 部署稳定化与监控 / 备份 / 回滚完善
8. 继续低批量观察 `refine-automation-publish-gates` 上线后的 warning 邮件、重复内容阻断、候选池门禁展示和自动发布结果

## 当前已知风险与待确认项

- 公开首页资讯流升级已部署生产；后续仍需观察真实访问、图片加载和自动发布内容在首页的长期表现
- 当前正式域名阶段仍以 HTTP 为主，HTTPS 证书尚未接入完成
- 需要把 HTTP 阶段的临时安全配置，在 HTTPS 切换时重新收紧
- 需要继续确认抓取调度、翻译调度、发布链路在正式域名环境下的长期稳定性
- 自动化发布涉及内容安全，生产首轮建议低频、低批量、保守开关启用
- AI 改写真实效果依赖模型配置与术语库质量，需继续通过后台人工抽检
- 邮件通知首版已实现；短信 / 微信通知当前只保留日志与配置位；QQ / OneBot 真实发送网关已在生产配置并通过测试消息，自动推送代码部署后即可灰度开启
- 需要补足更标准的部署基线、回滚与备份演练
- QQ Bot 正式自动推送链路仍需在本 change 部署迁移后开启 `QQ_PUSH_ENABLED=true` 并用测试群验收。

## 2026-06-23 QQ 群自动推送 OpenSpec change

### 当前实现

- 新增 OpenSpec change：`add-qqbot-auto-push`。
- 新增自动 QQ 推送交付模型，以“文章 x QQ 群”为唯一粒度记录状态、尝试次数、最大尝试次数、错误类型、错误信息、OneBot 响应、消息 ID、最后尝试时间和成功时间。
- 自动推送默认关闭：`QQ_PUSH_ENABLED=false`。
- 自动推送默认范围：`QQ_PUSH_SCOPE=high_value_only`，首版高价值口径为 `score_total >= AUTO_REVIEW_THRESHOLD`；也支持 `all_public`。
- 发布入口已接入自动推送入队：人工发布、`publish_article()` helper 和自动发布成功后都会在开关开启时异步进入 QQ 推送编排。
- 推送前检查 `SITE_URL + article.public_path` 是否可访问；URL 不可访问和 OneBot 发送失败分别记录为 `url_unavailable` 与 `send_failed`。
- 自动交付会先原子领取尝试再执行 URL 检查和 OneBot 发送，避免重复任务并发消耗重试次数。
- OneBot HTTP 200 但 JSON 返回业务失败时按 `send_failed` 记录，不会误标记为成功。
- `sending` 状态超过 `QQ_PUSH_SENDING_STALE_SECONDS`（默认 600 秒）后允许后续任务重新领取，避免 worker 异常后长期卡住。
- 自动推送只读取 `PushTarget.is_active=true` 的群；`is_default` 保留给后台手动推送默认目标。
- Django Admin 新增自动交付记录查看入口，并在文章详情中展示交付内联记录。

### 当前启用策略

- 生产已配置 NapCatQQ / OneBot v11 网关、测试群和 access token。
- 生产 `.env` 已设置 `QQ_PUSH_SCOPE=all_public`，目标是测试群阶段推送所有公开新闻。
- 部署代码和迁移前保持 `QQ_PUSH_ENABLED=false`；确认 `QQPushDelivery` 可用后再设置 `QQ_PUSH_ENABLED=true`，重启 `worker/beat` 灰度观察。
- OneBot API 不得公网裸露；优先 Docker 内网 `http://onebot:3000`，临时映射只能绑定 `127.0.0.1`。

### 待验收

- 部署迁移后开启 `QQ_PUSH_ENABLED=true`。
- 发布或复用一篇公开文章触发测试群自动推送。
- 生产 `QQPushDelivery` 记录与 worker 日志核对。

## 2026-06-24 自动发布门禁优化本地实现

- OpenSpec change：`refine-automation-publish-gates`，当前 `tasks.md` 已完成本地实现和验证。
- 新增配置：
  - `AUTO_REWRITE_ENABLED=false`：默认跳过 AI 改写前置。
  - `AUTO_PUBLISH_CONTENT_SOURCE=base_translation`：默认使用基准翻译稿作为自动发布内容源。
  - `HIGH_VALUE_SOURCE_RULES=netkeiba:access,netkeiba:attention`：访问量榜和注目数榜评分阶段放行。
  - `AUTOMATION_WARNING_NOTIFY_EMAILS=754652181@qq.com`：高价值 warning 初期告警收件人示例。
- 新增数据字段：
  - `NewsArticle.gate_issues` 保存结构化门禁 issue。
  - `WorkflowStatus.DUPLICATE` 描述高度重复内容。
  - `duplicate_of / duplicate_score / duplicate_reason` 保存重复检测解释。
  - `automation_warning_email_signature / automation_warning_email_sent_at` 用于 warning 邮件 24 小时去重。
- 迁移 `0009_automation_publish_gates` 会导入首批非马名普通词固定译法，包括 `タイトル`、`メートル`、`オッズ`、`ハンデ`、`ラジオ`、`ダート`、`マイル`、`スプリント`、`クラス`、`チャンス`、`キャリア`、`イメージ`、`デビュー`、`ゲート`。
- 后台候选列表、候选详情、自动化日志和 Django Admin 已展示 blocker / warning / info、重复检测结果和相似文章信息。
- `2026-06-24` review 返修：
  - 重新校验通过且当前不再重复的文章，会清理旧 `duplicate_of / duplicate_score / duplicate_reason`，并把旧 `duplicate` / `pending_review` 状态恢复为可进入自动发布批次的候选状态，避免显示 `publish_ready` 但被批发布排除。
  - 候选列表与候选详情中的相似文章现在链接到后台候选详情 `/admin/candidates/<id>/`。
- 本地验证：
  - `DB_ENGINE=sqlite /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py check`：通过。
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py test stable.tests.AutomationFlowTests stable.tests.ConsoleFlowTests --noinput`：通过，23 项。
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py test stable --noinput`：通过，106 项。
  - `openspec validate refine-automation-publish-gates --strict`：通过。

### 生产上线结果

- PR：GitHub PR #4 `[codex] refine automation publish gates` 已 squash merge。
- 生产提交：服务器 `/opt/umanewsbot` 已从 `71ab966` 更新到 `42a4622`。
- 部署前 `.env` 备份：`.env.backup.refine-automation-20260624_013323`。
- 已设置生产灰度配置：
  - `AUTO_REWRITE_ENABLED=false`
  - `AUTO_PUBLISH_CONTENT_SOURCE=base_translation`
  - `HIGH_VALUE_SOURCE_RULES=netkeiba:access,netkeiba:attention`
  - `HIGH_VALUE_WARNING_SCORE_THRESHOLD=90`
  - `AUTO_DUPLICATE_LOOKBACK_DAYS=7`
  - `AUTO_DUPLICATE_HIGH_THRESHOLD=0.86`
  - `AUTO_DUPLICATE_REVIEW_THRESHOLD=0.72`
  - `AUTOMATION_WARNING_EMAIL_ENABLED=true`
  - `AUTOMATION_WARNING_NOTIFY_EMAILS=754652181@qq.com`
  - `AUTOMATION_WARNING_EMAIL_DEDUP_HOURS=24`
- 容器：`web` healthy，`db / redis` healthy，`worker / beat` up。
- 迁移：`stable.0009_automation_publish_gates` 已应用；运行时确认 `WorkflowStatus.DUPLICATE=True`，首批 `non_horse_common_word` 普通词种子数量为 `14`。
- 验证：
  - `docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py check`：通过。
  - `http://umafans.run/healthz/` 返回 `200`。
  - `http://umafans.run/` 返回 `200`。
- 部署注意：重启初期日志曾出现一次 `automation_warning_email_sent_at` 字段已存在异常，判断为容器启动自动迁移与手工迁移并发撞车；后续日志显示 `No migrations to apply`，`showmigrations stable` 显示 `0009` 已应用，服务健康检查持续返回 `200`。

## 2026-06-23 前台发布判定代码阅读结论

- 公开前台首页 `/` 与详情页 `/news/<slug>/` 只展示 `workflow_status=published` 且 `published_to_web_at` 非空的 `NewsArticle`。
- 抓取入库的新稿默认是 `workflow_status=pending_translation`，不会因为来自 `netkeiba` 新着、访问榜、注目榜或 `JRA` 官方新闻而直接进入前台。
- 翻译成功后文章进入 `pending_edit`；若 `AUTOMATION_ENABLED=true`，会触发自动化评分、改写与校验链路。
- 自动化评分为 `auto` 的文章也不会立刻公开；必须完成改写、通过一致性校验成为 `automation_status=publish_ready`，再由批量自动发布任务写入 `workflow_status=published` 与 `published_to_web_at` 后才进入前台。
- 自动化硬规则会把重复稿、正文过短或为空、疑似乱码/结构损坏、疑似广告或导航短页直接置为 `ignored`，默认不进入前台。
- 长采访或引语较多、翻译未成功、缺少基准中文翻译等会转为 `manual` / `pending_review`，需要人工审核后发布。
- 人工发布通过运营后台文章编辑页完成时会写入 `workflow_status=published`、`published_to_web_at`、`published_by_mode=manual`；无封面时需要二次确认。Django Admin 或后台 API 若只改 `workflow_status` 而不补 `published_to_web_at`，仍不会被公开前台接收。

## 2026-06-23 外部赛马数据导入 OpenSpec 提案

- 已创建 OpenSpec change：`add-netkeiba-horse-data-import`。
- 提案目标：使用 `keibascraper` / netkeiba 作为低频离线导入来源，先抓取近两年比赛、出走、赛果、赔率、马匹血统和马匹履历数据，保存结构化字段与原始 payload，并派生本地马名索引。
- 关键约束：导入默认关闭，不加入自动全量调度；生产必须人工显式执行、强制限速、随机抖动、小批量、可暂停、可恢复；导入失败不得影响新闻抓取、翻译、自动化发布或公开前台。
- 当前状态：仅完成 proposal、design、delta spec 和 tasks，尚未实现代码，尚未执行真实爬取。

## 2026-06-19 公开首页资讯流升级 OpenSpec 主 change

### 已归档产物

- 正式规格：`openspec/specs/public-home-info-feed/spec.md`
- 归档目录：`openspec/changes/archive/2026-06-22-upgrade-public-home-info-feed/`
- 归档内保留 proposal、design、delta spec、tasks 和 `.openspec.yaml`

### 主范围

- Web 端：首页升级为轻导航、主头条、普通新闻流和右侧热门/重点辅助模块。
- 移动 H5：首页升级为轻顶部、轻量头条和高密度左文右图新闻列表。
- 数据层优先复用现有 `NewsArticle`、`NewsSnapshot` 与自动评分字段，不新增数据库模型。
- 公开站点样式从后台 `console.css` 中解耦，后续实现应新增公开站点专用样式入口。
- 文章详情页与首页共享公开站点视觉体系，并保持已有有效稿件字段优先级。
- 后续实施采用严格 TDD：发布过滤、普通流排序、头条选择、热门代理、详情页字段和公开静态资源必须逐行为执行 RED -> GREEN -> REFACTOR，禁止一次性批量写完全部测试后再实现。
- 热门代理必须在有限候选集内批量读取 `NewsSnapshot` 或使用等价预取方式，避免无上限扫描或逐篇文章查询最近快照。

### 明确非目标

- 不做原生 App、个性化推荐、无限滚动、站内浏览量、站内评论或用户系统。
- 不在本轮新增手工置顶、推荐位、专题、搜索频道或赛事日历模型。
- 不改抓取、翻译、AI 改写、自动发布、QQ 推送或 Docker Compose 主架构。

### 本地实现结果

- 公开首页 `/` 已升级为公开站点专用模板和 `stable/public.css`，不再以后台 `console.css` 作为主要样式入口。
- 首页数据层复用现有 `NewsArticle`、`NewsSnapshot` 与自动评分字段，提供 `headline_article`、`feed_articles`、`latest_articles` 和 `hot_articles`。
- 头条选择按近期范围、赛事优先级、自动评分、封面和发布时间排序；低量内容回退到近 7 天或最新已发布文章。
- 热门代理在有限已发布候选集内批量读取上游访问/注目快照，无快照时按自动评分和发布时间回退；页面只标注“原站热度/原站排行”，不包装为本站评论或浏览量。
- 移动 H5 首页采用轻头条 + 左文右图高密度列表，普通卡片在 390px 视口验收中稳定为约 128px 高，缺图卡不破坏列表布局。
- 详情页复用公开站点 base，继续展示有效标题、摘要、正文、来源、原文链接和发布时间，并完成窄屏阅读排版验收。
- 本轮未新增数据库模型、迁移、生产配置或部署运行手册步骤。

### 校验结果

- `openspec validate upgrade-public-home-info-feed --strict`：归档前通过。
- `openspec validate --all`：归档前通过；归档并同步正式 spec 后再次通过。
- `/plan-eng-review upgrade-public-home-info-feed`：通过。
- `DB_ENGINE=sqlite /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 manage.py test stable.tests.PublicHomeInfoFeedTests`：通过，10 项。
- `DB_ENGINE=sqlite /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 manage.py check`：通过。
- `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 manage.py test stable`：通过，88 项。
- 本地开发服务器浏览器验收：桌面首页、移动首页、桌面详情页、移动详情页通过；无横向溢出，图片加载正常，移动普通卡高度受控，桌面主列与右侧热门模块不重叠。

### 生产部署结果（2026-06-22）

- GitHub PR #1 从 draft 转为 ready 后合并到 `main`，merge commit 为 `e834f58`，包含实现提交 `1c9be7d`。
- 服务器 `/opt/umanewsbot` 从 `62a6a02` 快进到 `e834f58`；部署前备份 `.env` 为 `.env.backup.20260622_140844`。
- 生产使用低成本 compose 执行 `./deploy_lowcost.sh`：重建 `web/worker/beat`，`migrate` 显示 `No migrations to apply`，`collectstatic` 成功处理 `stable/public.css`，`web` 容器 healthy。
- 外部健康检查通过：`http://umafans.run/healthz/` 与 `http://umafans.run/` 均返回 `200`。
- 首页 HTML 已引用 `/static/stable/public.2eec24723b45.css`，页面包含 `home-page`、`headline-card`、`news-card` 和“原站热度”；不再引用后台 `console.css`。
- 浏览器生产验收通过：桌面端显示轻导航、头条和热门模块；390px 移动端普通新闻卡约 `128px` 高，首屏头条后可见 3 条普通新闻，无横向溢出；新闻详情页可打开，标题、封面和公开详情结构正常，控制台无错误。

### 移动端首屏密度 follow-up（2026-06-22）

- 在不改变首页数据层、公开 URL、模板结构或普通新闻卡尺寸的前提下，后续小幅收紧移动端首页视觉密度。
- 调整范围仅限 `server/stable/static/stable/public.css` 的 `max-width: 599px` 移动端规则：
  - 顶部和页面内边距略收紧。
  - 移动端头条图片从 `16 / 9` 改为 `16 / 7`。
  - 移动端头条摘要隐藏，仅保留来源时间和两行标题。
  - 普通新闻卡继续保持约 `128px` 高和右侧缩略图结构。
- 本地临时 SQLite + 浏览器验收结果：390px 视口下头条高度约 `250px`，第一张普通新闻卡提前到 `top=381`，首屏可见 4 条普通新闻卡，无横向溢出，控制台无错误。
- 生产部署结果（2026-06-23）：GitHub PR #2 合并到 `main`，merge commit 为 `04e2ee9`；服务器 `/opt/umanewsbot` 从 `e834f58` 快进到 `04e2ee9`，部署前备份 `.env` 为 `.env.backup.20260623_120201`。
- 生产 `./deploy_lowcost.sh` 执行成功：`migrate` 显示 `No migrations to apply`，`collectstatic` 后首页引用 `/static/stable/public.9aaf4b105424.css`，`web` 容器 healthy。
- 外部健康检查通过：`http://umafans.run/healthz/` 与 `http://umafans.run/` 均返回 `200`；首页包含 `home-page`、`headline-card`、`news-card` 和“原站热度”，不再引用 `console.css`。
- 浏览器生产验收：390px 移动端头条约 `257px` 高，第一张普通新闻卡 `top=388`，普通卡约 `128px` 高，首屏可见 4 条普通新闻卡，无横向溢出；详情页公开结构、封面和标题正常，控制台无错误。

## 2026-06-07 术语候选发现生产部署纪要

### 部署内容

- 服务器 `/opt/umanewsbot`：`git pull origin main` 从 `7123e4e` 快进到 `e2e3e07`
- 迁移 `0006`（纯新增 `TermCandidate` / `TermCandidateEvidence` 两表）已应用；`web` 启动脚本会自动迁移，显式 `migrate` 显示 `No migrations to apply`
- `.env` 追加并保持关闭：`TERM_DISCOVERY_ENABLED=false` / `TERM_DISCOVERY_PROVIDER=rules` / `TERM_DISCOVERY_MIN_CONFIDENCE=60`
- 用低成本 compose `docker-compose.prod.lowcost.yml` 重建 `web/worker/beat`，`db/redis/nginx` 未动

### 迁移前备份（可回滚）

- `.env.backup.20260607_033207`
- 数据库快照 `backups/pre-0006-20260607_033207.sql`（74M，`horse_news` 库，含 `PostgreSQL database dump complete` 标记）

### 上线后验证

- 容器 `web/db` healthy、`worker/beat` up；`manage.py check` 0 issues
- 候选/证据模型可查、计数 `0/0`；`nginx → web` 与外网 `umafans.run` / `www.umafans.run` 均 `200`
- `worker` 近 200 行日志无报错；核对 `AUTOMATION_ENABLED=true`、`REWRITE_PROVIDER=siliconflow` 未变更

### 回滚方式

- 停用功能：将 `TERM_DISCOVERY_ENABLED=false`（当前即为关闭），重启 `web` 与 `worker` 即可，无需回滚迁移或删除候选数据
- 整体回退：用上面的 `.env` 备份与数据库快照还原

## 最近一次翻译稳定性修复

- 现象：部分文章翻译失败，错误为 `Translation response changed unknown horse names`
- 原因：未知马名校验过于严格；模型没有原样保留疑似未收录马名时，系统会让整篇翻译失败
- 修复：
  - 翻译 prompt 中对未知马名使用 `__UMA_KEEP_n__` 占位符保护
  - 模型返回后将占位符还原为原始日文马名
  - 若模型仍未保留未知马名，不再让整篇失败，而是写入 metadata warning 后接受译文
- 验证：
  - 新增未知马名占位符还原测试
  - 新增未知马名仍缺失但不阻断翻译的测试
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable` 通过，45 项

## 自动化内容运营 MVP 开发纪要

### 本轮新增能力

- `NewsArticle` 增加自动化字段：分流模式、风险等级、自动化状态、评分、决策原因、基准翻译稿、改写稿、自动发布时间与错误信息
- 新增 `AutomationLog`，记录评分、改写、校验、发布、通知各阶段过程
- 新增 `NotificationLog`，记录邮件 / 短信 / QQ / 微信通知状态；MVP 真实发送只启用邮件
- 新增自动化服务：
  - `stable.services.automation`
  - `stable.services.rewriting`
  - `stable.services.validation`
  - `stable.services.notifications`
- 新增 Celery 任务：
  - `process_article_automation_task`
  - `score_article_task`
  - `rewrite_article_task`
  - `validate_rewrite_task`
  - `auto_publish_batch_task`
  - `send_notification_task`
  - `detect_automation_anomalies_task`
  - 新增 Celery Beat 调度：
    - 每 15 分钟批量自动发布
    - 每 30 分钟检测自动化异常
  - 自动发布批量规则已调整为：
    - 常规时段每批最多 4 篇
    - 每周日北京时间 13:00-16:00 每批最多 10 篇
    - 调度频率仍为每 15 分钟一次

### 当前验证结果

- `DB_ENGINE=sqlite python manage.py check`：通过
- `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable`：通过，40 项测试

### 生产启用前注意

- 必须先部署代码并执行迁移 `python manage.py migrate`
- 初次部署建议 `AUTOMATION_ENABLED=false`
- 确认后台可看到自动化字段和日志后，再切换 `AUTOMATION_ENABLED=true`
- 当前自动发布策略为常规每批 4 篇、周日 13:00-16:00 每批 10 篇，并定期人工抽检自动发布稿

## 专有术语候选发现与待标注池

### 当前实现

- 新增 `TermCandidate` 与 `TermCandidateEvidence`，分别保存待审核术语和按文章聚合的来源证据。
- 首版支持马名、比赛名、骑手名和马主名四类实体。
- 新文章入库后可旁路触发发现任务；发现失败不会阻断抓取、翻译、改写或发布。
- 候选会与正式 `TermEntry.source_ja`、日文别名及已有候选去重；停用正式术语也参与去重。
- 后台新增“术语候选”列表、详情、单篇重新发现、接受、修改后接受、合并、拒绝、忽略和保守批量拒绝/忽略。
- 规则或 AI 发现结果不会直接写入正式术语库，只有工作人员明确接受后才创建 `TermEntry`。

### 当前启用策略

- `TERM_DISCOVERY_ENABLED=false`：默认关闭。`2026-06-07` 已在生产应用迁移并部署代码，当前处于“先关后开”灰度阶段，待单篇抽检后再开启。
- `TERM_DISCOVERY_PROVIDER=rules`：首版使用保守规则发现器。
- `TERM_DISCOVERY_MIN_CONFIDENCE=60`：低于阈值的发现结果不进入候选池。

### 当前验证结果

- `DB_ENGINE=sqlite python manage.py check`：通过。
- `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable`：通过，69 项。
- `openspec validate --all`：通过。
- 两种生产 Compose 配置基于 `.env.example` 检查通过。
- 已使用独立 SQLite 数据库部署本地验收环境，并通过浏览器完成筛选、单篇重跑、接受、合并、拒绝、忽略、批量操作、操作日志和别名搜索验收。

## 最近一次关键修复纪要

### 现象

- 域名已经解析到服务器 IP
- HTTP 请求被 `301` 跳转到 HTTPS
- HTTPS 请求返回 `400 Bad Request`
- 浏览器无法正常打开正式域名页面

### 排查过程

- 先确认 DNS 是否已经真正打通，排除“域名未解析”的假象
- 再比对仓库当前代码与服务器实际 `HEAD`
- 检查服务器 `.env` 中的 `ALLOWED_HOSTS`、`SITE_URL`、`SECURE_SSL_REDIRECT` 等关键项
- 进入 `nginx` 容器读取真实 `/etc/nginx/conf.d/default.conf`
- 检查 `web` 容器运行态环境变量与日志
- 最终确认线上实际行为与仓库当前预期不一致

### 确认的真实根因

- 服务器并未运行到本地最新域名接入修复版本
- 服务器仍在使用旧版 `nginx` 配置，保留 `80 -> 443` 跳转与启用中的 HTTPS server block
- 服务器 `.env` 仍使用旧版 IP + HTTPS 强制配置
- `ALLOWED_HOSTS` 未包含正式域名，导致域名下请求被 Django 拒绝

### 修复动作

- 备份服务器 `.env`
- 清理或暂存本地未提交运行态差异
- 将服务器代码同步到正确版本
- 更新 `.env`，切换为正式域名 + HTTP 阶段配置
- 重建并启动 `web / worker / beat / db / redis / nginx`
- 进入容器核对真实 `nginx` 配置与环境变量，确保运行态与仓库一致

### 修复后验证结果

- `nginx` 容器加载了新版 `default.conf`
- `80 -> 443` 强制跳转已移除
- 正式域名 `umafans.run` / `www.umafans.run` 页面可打开
- 线上服务恢复到与当前仓库预期一致的状态

### 后续如何避免再次发生

- 每次部署前先确认服务器 `HEAD`，不要只看本地仓库
- 每次域名或安全策略变更时，同时核对：
  - 仓库代码
  - 服务器 `.env`
  - `nginx` 容器内真实配置
  - `web` 容器内真实环境变量
- 不把聊天记录当唯一记忆来源，关键修复过程必须落文档
- 生产问题处理时，坚持“先核对运行态，再给结论”

## 2026-06-23 外部赛马数据导入实现状态

### 本地已实现

- 新增 OpenSpec change：`add-netkeiba-horse-data-import`。
- 新增 `keibascraper==3.1.5` 依赖，并通过管理命令提供 import 冒烟检查入口。
- 新增外部赛马数据表：比赛、出走表、赛果、赔率、马匹、马匹履历、马名索引、导入运行、导入错误和单来源导入锁。
- 新增 `stable.services.external_horse_data`：
  - 包装 `keibascraper.race_list()` 与 `keibascraper.load()`。
  - 项目侧强制执行网络开关、请求间隔、随机抖动。
  - 保存结构化字段与 `raw_payload`。
  - 对比赛、出走、赛果、赔率、马匹、履历做幂等 upsert。
  - 从出走表、赛果、可信单马参数派生 `ExternalHorseAlias`。
  - 单马导入仅在存在可信马名时创建马名索引，避免凭空写入错误马名。
  - 记录覆盖率统计：比赛数、出走数、赛果数、赔率数、马匹数、履历数、唯一马 ID、唯一日文马名、缺失马 ID/马名记录数。
- 新增管理命令 `import_external_horse_data`：
  - 支持默认近两年、指定年月、指定 `race_id`、指定 `horse_id`、`--horse-name`、`--dry-run`。
  - 支持 `--max-races`、`--max-horses`、`--fetch-odds`、`--no-fetch-horse-detail`。
  - 支持 `--lookup-name` 查询本地马名索引。
  - 支持 `--stats-run-id` 查看导入运行统计。
  - 支持 `--check-dependency` 检查 `keibascraper` 是否可 import。
- 新增 Celery 任务 `import_external_horse_data_task`，但未加入默认 Celery Beat 全量调度。

### 当前默认策略

- `EXTERNAL_HORSE_DATA_IMPORT_ENABLED=false`。
- `EXTERNAL_HORSE_DATA_ALLOW_NETWORK=false`。
- 代码已可部署迁移，但生产不会自动发起 netkeiba 请求。
- 外部数据导入当前不参与新闻抓取、翻译、AI 改写、自动发布或公开前台。

### 本地验证

- `DB_ENGINE=sqlite python manage.py check`：通过。
- `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable.tests.ExternalHorseDataImportTests`：通过，8 项。
- `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable`：通过，96 项。

### 生产执行提醒

- 生产首次真实导入前必须备份数据库。
- 先执行 dry-run 或单月小批量。
- 首次真实请求建议使用 8-10 秒间隔、小批量、低峰时段，不抓赔率。
- 同一来源通过导入锁避免多 worker 并发放大请求。
- 如发现异常，优先关闭 `EXTERNAL_HORSE_DATA_IMPORT_ENABLED` / `EXTERNAL_HORSE_DATA_ALLOW_NETWORK` 并停止任务；新表不参与主新闻链路。

### 生产首轮小批量导入结果

- 生产部署提交：`58a6e82`。
- 部署前 `.env` 备份：`.env.backup.external-horse-data-20260623_231514`。
- 服务器迁移：`stable.0008_externaldataimportrun_externaldataimportlock_and_more` 已应用。
- 容器内依赖检查：`keibascraper import ok`。
- dry-run：`2026-05` 单月、小批量、最多 10 场，预计 20 个请求。
- 真实导入命令：`2026-05`、`--max-races 10`、`--max-horses 30`、不抓赔率、不补马匹详情、请求间隔 10 秒 + 2 秒抖动。
- 运行结果：`run_id=1`，`status=paused`，`success_count=10`，`failure_count=0`，`skipped_count=326`。
- 写入统计：`race_count=10`、`entry_count=151`、`result_count=143`、`horse_count=143`、`unique_horse_id_count=143`、`unique_horse_name_count=143`、`missing_horse_id_or_name_count=16`。
- 样本马名索引已写入，如 `ヴォルスター`、`ファイツオン`、`サトノエピック`。

### 后续继续导入注意

- `2026-06-24` 已补充按月续跑逻辑：再次导入同一月份时会先跳过已落库的 `ExternalRace.race_id`，只处理下一批未导入 race。
- 不建议直接一次性跑近两年全量；应继续按月、小批量、低速运行，并观察失败率和覆盖率。

### 生产第二批续跑结果

- 续跑部署提交：`a61d789`。
- 第二批真实导入：`run_id=2`，同为 `2026-05`，最多 10 场，不抓赔率，不补马匹详情，10 秒间隔 + 2 秒抖动。
- 续跑确认：`parameters.already_imported_race_count=10`，说明第二批已跳过首批落库 race。
- 运行结果：`status=paused`，`success_count=10`，`failure_count=0`，`skipped_count=316`。
- 累计写入统计：`race_count=20`、`entry_count=292`、`result_count=274`、`horse_count=274`、`unique_horse_id_count=274`、`unique_horse_name_count=274`、`missing_horse_id_or_name_count=36`。

### 生产第三批续跑结果

- 第三批真实导入：`run_id=3`，仍为 `2026-05`，最多 30 场，不抓赔率，不补马匹详情，10 秒间隔 + 2 秒抖动。
- 运行结果：`status=paused`，`success_count=30`，`failure_count=0`，`skipped_count=286`。
- 累计写入统计：`race_count=50`、`entry_count=742`、`result_count=695`、`horse_count=695`、`unique_horse_id_count=695`、`unique_horse_name_count=695`、`missing_horse_id_or_name_count=94`。
- 服务器健康检查：`/healthz/` 返回 `200`。

### 生产长循环导入中断记录

- `2026-06-24` 按用户确认启动长循环：从 `2026-05` 到 `2025-06`，每批 25 场，不抓赔率，不补马匹详情，10 秒间隔 + 2 秒抖动。
- 成功完成批次：`run_id=4` 到 `run_id=8`，均为 `2026-05`，每批 25 场，均 `failure_count=0`。
- 中断批次：`run_id=9`，`2026-05`，已成功 7 场后执行进程以退出码 `137` 中断；当时 `web/db` 容器发生重启，但 `OOMKilled=false`。
- 已人工收尾：将 `run_id=9` 标记为 `partial`，写入 `finished_at` 和 coverage，释放 `ExternalDataImportLock`。
- 中断后累计写入：`race_count=182`、`entry_count=2692`、`result_count=2518`、`horse_count=2401`、`unique_horse_id_count=2401`、`unique_horse_name_count=2401`、`missing_horse_id_or_name_count=348`。
- 当前服务状态：`web/db/redis/nginx/worker/beat` 运行，`/healthz/` 返回 `200`。按“报错退出则停止”约定，未继续启动后续导入。
