# 新地区新闻抓取设计

## 0. 最新主线集成状态

本设计已经通过独立方案审核（`VERDICT: APPROVED`），并在
`/Users/mentianlu/Code/umanews/.worktrees/add-new-region-news-sources-release-candidate`
完成第三次 main 无提交集成。目标分支为
`codex/add-new-region-news-sources-release-candidate`；集成时点基线与 HEAD 均为
`a122ff6dde16ab4b53f34e446b0f959751ad7a77`，`origin/main..HEAD=0`。此前 integrated、
main-integrated 和 final-integrated worktree 继续保留为回退副本，不作为最终验收入口。

当前实现结果：

- `InternalSiteOnlyMiddleware`、受保护 local media/私有 OSS 预检、QQ/PushLog/内容通知外发
  硬门和 translation/rewrite 外部 AI 总门已经实现。
- 默认 `SITE_INTERNAL_ONLY_ENABLED=true`、
  `NEWS_EXTERNAL_AI_PROCESSING_ENABLED=false`。`DEBUG=false` 的内部模式必须启用 secure
  session/CSRF cookies；传输层只接受 direct `SECURE_SSL_REDIRECT=true`，或显式
  `SITE_INTERNAL_ONLY_TRUSTED_TLS_TERMINATION=true` 且具有合法
  `SECURE_PROXY_SSL_HEADER` HTTPS 合同。认证 local media/私有 OSS 短签名仍是硬门，任一
  不安全组合都 fail closed。
- 来源级 `usage_scope=internal_only` / `public_publish_allowed=false` 是独立内容门，关闭
  全局站点登录墙不会提升稿件。公开 queryset、详情和 QQ 必须共用文章级 blocker。
- 外部 AI 关闭时 translation retry selector 在 claim 前跳过，preclaim 兼容入口会释放
  article/run 状态，batch skipped 不增加 translated。通知 sanitizer 只保留安全 counts/IDs，
  删除来源 URL 与内容；翻译失败耗尽通知为 `article_id`-only。TDN listing skip metrics 与
  probe canonical normalize/拒绝原因使用 ingestion 同一口径。
- 本设计第 15.4 节列出的 12 个第三批 adapter/SourceSite/NewsSource 已实现，均保持
  `enabled=false / production_approved=false`；Google News discovery 仍排除在本批。
- 最新迁移临时库受控 live probe 已把 24-source registry 验证为
  `16 accepted / 8 blocked`；JCSA、Racing Victoria 为 accepted，HRI、Woodbine、ERA 因
  端到端 `missing_published_at` 保持 blocked。accepted 只表示 internal-only 技术池，不是
  启用或生产批准。
- 日期精度使用统一分类器：可信的来源当地发表日与当地抓取日相差 `0/1` 天进入候选，
  `>1` 天归历史；无可信时间或 evidence/precision/时区无效归 `unresolved`，在 upsert 前停止。
- 当前 `a122ff6…` 候选的 migration DAG 功能路径为双 `0047` ->
  `0048_merge_20260719_2242.py` ->
  `0049_alter_newsarticle_source_site_and_more.py`；main 新增
  `0048_raceeventrunner_external_runner_identity.py`，最终由无操作
  `0050_merge_20260720_0017.py` 合并为该基线唯一 leaf。migration check/plan/测试库 migrate
  通过；第三次 main 集成后复核仍为唯一 leaf。
- 首次独立代码审核为 `REVISE (2 P1 + 5 P2)`；七项 finding 取得
  `7 failures / 0 errors` 的真实 RED，修复后 `7/7`。同一 reviewer session 实质确认修复
  `APPROVED`，但 main 漂移令完整性门禁 `BLOCKED`；候选已重新集成到
  `origin/main@a122ff6d…`，仍须复审最终精确版本。
- 最新 release-candidate 离线组合为 `214/214 OK`、follow-up `10/10`，migration 无漂移且 Django
  checks 通过；来源实现代理另报告 `202` 组合加 `1 skip`、translation recovery `22/22`。
  第二轮的 `175/175`、release-gate `69 OK` 和 race-live `37/37 + 63/63` 保留为不同集合的
  历史集成证据。

这些结果只证明本地 SQLite/配置集成，不是发布证据。当前仍未 commit、push、创建 PR、部署、
应用生产迁移或启用来源。第三批 live probe、最近六小时汇总和 dummy 翻译编排已经完成；
真实中文远程模型、PostgreSQL 专项、生产 TLS/私有 media 验收、最终精确
版本复审和用户新授权仍未完成。

### 0.1 第三轮 live evidence

- 运行环境：已迁移的仓库外 `/tmp` SQLite；透明 bounded HTTP；每源 listing `1`、detail
  最多 `2`；零生产读写。首次空库 `no such table` 仅为环境错误，迁移后重跑才是来源结论。
- 24-source registry：
  - accepted `16`：RTÉ、IrishRacing、Dubai Racing Club、JCSA、SPA、Racing Victoria、
    Just Horse Racing、The Straight、Racing NSW、Tasracing、TDN、BloodHorse、
    Horse Racing Nation、Sky Sports Racing、Sporting Life、BHA；
  - blocked `8`：HRI、Woodbine、Canadian Thoroughbred、Assiniboia Downs、ERA、
    The National、Arab News、Paulick Report。
  全部 `usage_scope=internal_only / public_publish_allowed=false`。
- 第三批 12 源为 `8 accepted / 4 blocked`。IrishRacing、SPA、Racing NSW、Tasracing
  根据 live 结构先取得回归 RED、最小修复后复探 accepted；Racing NSW listing/detail
  额外排除 tips/preview，generic `Latest News` 不覆盖 RSS title。四个 blocked 为
  Canadian Thoroughbred、Assiniboia Downs、The National、Arab News。
- technical status 取决于透明请求下的端到端 listing/detail 正文与可用时间合同，不以
  listing HTTP `200` 代替。HRI/Woodbine/ERA 因 `missing_published_at` blocked；TDN E2E
  正文成功后 accepted，但当前样本时间 unverified，freshness candidate 仍 deferred。
- latest probe 约 `2026-07-19T17:41Z`。严格六小时约
  `11:41Z..17:41Z`，只有 Ireland `2`：RTÉ
  `Power Blue back to winning ways at the Curragh`（`15:09:15Z`，verified）与
  IrishRacing `Tokyo Tower shows resolution to land Curragh finale`
  （`16:51:00Z`，verified）。其余五目标地区中 Canada/UAE/Saudi/Australia 均为 `0`。
  TDN `17:28:05Z` unverified、JHR `10:09:13Z` 超窗，其余来源日期/时刻更早，均不计。
  所有本轮样本都有精确时间，date-only `0/1` 日合同未被用于增加六小时数量。
- 复用归属离线测试确认 Curragh/Irish Oaks -> Ireland、Woodbine/Canadian -> Canada；
  无强关键词保持原 US/UK region。Sporting Life technical accepted 但样本时间 unverified，
  候选 deferred。
- 同一临时库以真实 RTÉ 正文 `6616` 字符和 `TRANSLATION_PROVIDER=dummy` 运行；
  `translate_article_task` 返回 `translated=true`，article status 为 `translated`，
  `TranslationRun=success`，标题带 `[未配置真实翻译模型]`。本机 SiliconFlow/OpenAI key
  均 absent，故只证明任务/持久化编排，不代表真实中文远程翻译完成。

## 1. 现状

新闻来源通过 `server/stable/services/sources.py` 同步到 `NewsSource`，内置国际来源由
`server/stable/adapters/international.py` 提供 adapter，`crawl_news_source_task` 建立
`CrawlJob`、解析详情、调用 `upsert_article_from_draft()`，随后进入翻译、术语发现和审核链路。

当前共享 `RacingRegion` 只有五个正式地区和 `other`。归属服务
`server/stable/services/news_attribution.py` 把爱尔兰命中追加成 `ireland` 标签并关联英国，
把澳大利亚、加拿大、沙特和迪拜等标题视为 out-of-scope 后归入 `other`。这不满足独立来源
健康、地区窗口、筛选和 QQ 订阅要求。

`RacingRegion` 同时被新闻、赛事、马匹和准实时链路复用。仓库存在若干
`RacingRegion.values/choices` 全枚举循环；如果只增加 choice 而不收紧这些消费者，会让新地区
意外进入历史赛事批次、准实时 initializer 或赛事日历。因此地区扩展必须同时完成能力集合隔离。

## 2. 设计目标与非目标

### 目标

- 在现有 Django 单体和国际新闻 adapter 体系内加入五个地区，不新建第二套抓取框架。
- 五地区分别有来源、归属、审计、筛选和订阅身份。
- 第一批每地区优先一个官方或官方赛马场来源，默认关闭、可单源回滚。
- 时间、正文、URL、来源身份和去重证据可审计。
- 新地区 choice 不改变结构化赛事和马匹任务的现有分母。

### 非目标

- 不接入新地区结构化赛事/马匹数据。
- 不批量重写历史文章。
- 不在本任务中启用生产抓取、自动发布、QQ 或归属 enforce。
- 不复制图片、视频、赔率或受限制数据。

### 2026-07-19 内部使用增量

本轮将产品边界改为“全部内容只向认证用户开放”。本文第 13–14 节保存的是此前 permission
门禁的实现和审核历史；从第 15 节开始使用新的技术准入/内部使用模型。旧代码不得直接删除，
而应以兼容迁移把历史三态映射到新的三轴审计，避免失去既有证据。

## 3. 地区模型

### 3.1 共享枚举继续使用，但消费者改为显式能力列表

在 `RacingRegion` 增加：

```python
IRELAND = "ireland", "爱尔兰"
CANADA = "canada", "加拿大"
UNITED_ARAB_EMIRATES = "united_arab_emirates", "阿联酋"
SAUDI_ARABIA = "saudi_arabia", "沙特阿拉伯"
AUSTRALIA = "australia", "澳大利亚"
```

不新增 `middle_east`。字符串长度均小于现有 `max_length=32`。

共享枚举仍表达赛马辖区的统一身份；业务范围不再从枚举全集推导，而由以下显式常量控制：

- `NEWS_ATTRIBUTION_REGIONS`：现有五区 + 新五区 + `other`
- `NEWS_PRODUCTION_REGIONS`：现有五区 + 新五区
- `RACE_DATA_REGIONS`：保持现有日本、香港、英国、法国、美国
- `HORSE_PROFILE_REGIONS`：保持现有明确范围
- `RACE_LIVE_SUPPORTED_REGIONS`：保持当前准实时来源 registry 允许范围

实施时以 `rg "RacingRegion\\.(values|choices)"` 和迭代 `RacingRegion` 的结果为清单，逐处判定
使用哪个能力集合。赛事日历只展示 `RACE_DATA_REGIONS`；历史批次和 live initializer 不再读取
枚举全集。这样将来扩展地区时不会再次隐式扩大不相关任务。

### 3.2 迁移

新增一条 schema migration，只更新 Django field choices，不执行历史数据更新，不创建
`middle_east` 行，也不把现有 `other`/英国文章自动改区。虽然 PostgreSQL 通常不会为 choices
创建数据库约束，仍使用正式 migration 保证 model state 一致，并运行
`makemigrations --check --dry-run` 验证无漂移。

迁移与新代码向前兼容：旧值保持有效；新来源在同步后仍关闭，因此迁移本身不产生抓取或发布。
代码回滚时优先关闭来源与窗口，不在已有新地区文章后回退到不识别新 choices 的旧应用。

## 4. 来源注册与 adapter

### 4.1 来源身份

新增五个 `SourceSite`：

- `hri_news`
- `woodbine_news`
- `emirates_racing_authority`
- `jcsa_news`
- `racing_victoria_news`

全部使用 `SourceMode.OFFICIAL`、`SourceLanguage.ENGLISH`，来源类型为官方或官方赛马场，
`enabled=false`、`production_approved=false`。来源同步继续保护运行态的启停、生产批准、
backoff、暂停和有效间隔。

### 4.2 adapter 结构

第一版复用 `SimpleInternationalNewsAdapter` 的请求、正文清洗和 canonical draft 结构，但每个
站点提供显式：

- 列表 anchor/URL 边界；
- 详情标题、正文、作者和日期 selector；
- 来源所在地 `ZoneInfo`；
- URL canonicalization；
- 内容类型/空正文/登录页/验证码识别；
- 发布时间 evidence。

不得依赖基类“列表项发布时间为 `timezone.now()`”的旧兜底。新 adapter 的 listing stub
发布时间允许为空或只作为未验证占位；详情归一化前必须取得可信时间，否则抛出可跳过的
`missing_published_at`，`_crawl_international_source()` 记录到来源摘要。若为满足类型契约需要
调整 `SourceArticleStub/CanonicalNewsDraft` 的 `published_at` 可空标注，数据库写入前仍必须
保证非空。

新来源共用一个有界 HTML 请求 helper，但不借此重构旧 adapter：

- 只接受 `https://`；
- 初始 host 和每次重定向后的最终 host 必须在 adapter 的静态 allowlist，最多 3 次重定向；
- 默认只接受 `text/html` 或 `application/xhtml+xml`；只有 Racing Victoria adapter 的固定
  sitemap URL 可显式加入 `text/xml`、`application/xml`；
- connect timeout 5 秒、read timeout 15 秒；
- 校验 `Content-Length` 并以 streaming 实际限制最大 2 MiB；
- 拒绝登录页、验证码/反机器人页、二进制和空响应；
- 使用可识别的项目固定 User-Agent，不复用浏览器品牌字符串，不做来源专属 UA 轮换、
  代理轮换或浏览器伪装。

测试覆盖 off-host redirect、非 HTML 200、超限正文、登录/验证码页和最终 URL；系统层既有
网络代理配置不在本 change 改写，但不得为绕过单源限制新增代理策略。

### 4.3 来源时区

- HRI：`Europe/Dublin`
- Woodbine：`America/Toronto`
- Emirates Racing Authority：`Asia/Dubai`
- JCSA：`Asia/Riyadh`
- Racing Victoria：`Australia/Melbourne`

结构化 ISO 时间自带 offset 时直接转 UTC；无 offset 的本地日期/时间按上述时区解析。仅日期
时可使用当地 12:00 作为排序时间，但必须标记 `precision=date`，不得伪装成精确发布时间。
完全没有日期则跳过。

### 4.4 真实页面补救设计

2026-07-19 的首轮有界 probe 证明通用 selector fixture 不足以代表真实来源。补救实现采用
逐源最小覆盖，不把五站差异继续堆进模糊的全局 selector：

- HRI：列表仅接收 `/news/details/`；canonical URL 先 HTML unescape，再对 Unicode
  空白等非 ASCII path 字符做稳定 percent-encoding；详情允许
  `Saturday, 20 June 2026` 这类来源限定长日期。
- Woodbine：列表仅接收 `/woodbine-news/`，排除 `/blog/` 和 `/news/` 根入口；详情优先读取
  `article:published_time` 或 JSON-LD `datePublished`，正文使用 `.entry-content`。
- Emirates Racing Authority：列表保持 `/news/` 文章路径；详情优先读取 JSON-LD
  `datePublished`，可回退到 `12 June 2026` 这类来源限定可见日期。
- JCSA：生产列表请求改为公开 HTML 片段 `/api/news/en/0/12`，展示主页仍为
  `/en/news/`；详情支持 `Saturday, 22nd February 2025, 9:00pm`，正文限定
  `.content-area`。不使用旧的 `/en/news/media-services/` 工具页。
- Racing Victoria：不在代码中保存或调用站点前端 GraphQL 凭据。列表使用
  `https://www.racingvictoria.com.au/sitemap.xml`，只接收带日期路径的正式文章 URL，
  排除 notices/videos/podcasts，并按 URL 日期倒序限量。真实透明 UA GET 已证明静态 HTML 的
  `#__next` 为空，详情数据位于 `script#__NEXT_DATA__`：
  `props.pageProps.layoutData.sitecore.route.fields.Title/ArticleDate` 提供标题和时间，
  `route.placeholders["headless-main"]` 递归下的 `componentName="RichText"`、
  `fields.Text.value` 提供 `<div class="ck-content">` 正文。解析必须限定在
  `headless-main`，排除 `headless-footer` 的 copyright RichText 和推荐列表组件。

共享日期提取只负责三个可审计来源：`meta[property=article:published_time]`、JSON-LD
`datePublished`、来源自有可见日期 selector。Racing Victoria 使用上述限定
`__NEXT_DATA__` 路径。JSON-LD 遍历限制在已识别的
`NewsArticle/Article` 节点；非 ISO 可见日期由各 adapter 声明格式白名单和本地时区，
解析证据记录 `source/raw/timezone/precision/parser_version/verified`。

有界请求 helper 引入携带 `status_code`、`final_url` 的专用异常或等价结构；adapter 在重新抛出
前更新 `last_listing_http_status/last_listing_final_url`，使 `403/429` 可被 probe 与 crawl
准确分类。`tasks._http_status_code_from_exception()` 同时读取 `exc.status_code` 和既有
`exc.response.status_code`；crawl 失败窗口的 `result_payload` 保存
`error_category/http_status/final_url`，`CrawlJob.error_message` 保留安全诊断字符串。

该 helper 只新增受限的 `user_agent` 与 `accepted_content_types` 参数，不接受任意 Cookie、
Authorization 或 Host headers：新五源显式传透明 UA；RV 只有 sitemap listing 调用传 XML
类型，detail 调用及其他四站仍只允许 HTML；未传参数时保持旧 `DEFAULT_HEADERS` 和旧 adapter
行为不变。

### 4.5 逐源准入

真实探测分为四层：

1. 条款/robots/登录/反自动化审核；
2. 列表页 HTTP、最终 URL、content-type、长度和样本 URL；
3. 详情标题、正文边界、可信时间、作者和语言；
4. 与数据库 URL/source ID 的重复比例。

探测命令不创建 `NewsSource`、`CrawlJob`、`NewsArticle` 或生产窗口，也不修改
`production_approved`。固定输出：

```json
{
  "source_key": "hri_news",
  "technical_status": "accepted",
  "automation_permission_status": "unknown",
  "effective_production_status": "production_blocked",
  "listing_url": "...",
  "final_url": "...",
  "adapter_version": "...",
  "parser_version": "...",
  "reviewed_at": "...",
  "artifact_sha256": "..."
}
```

只有 `technical_status=accepted` 且 permission `approved` 才能得到 effective `eligible`。
条款未知、过期或阻断时，即使解析成功也保持 `production_blocked`。artifact hash 绑定除自身
hash 字段外的 canonical JSON 和最小样本摘要。

本轮许可状态固定为：

- `hri_news=blocked`
- `woodbine_news=blocked`
- `emirates_racing_authority=blocked`
- `jcsa_news=unknown`
- `racing_victoria_news=unknown`

这些状态写入 adapter/probe 合同和来源说明，但不修改数据库中的
`NewsSource.production_approved`。后续只有新的书面许可证据才能把 blocked/unknown 改为
approved；技术解析成功不能自动提升许可。

许可也是网络执行门禁：

- HRI/Woodbine/ERA 当前只做离线 fixture 修复，取得新书面许可前禁止再次联网 probe，
  技术状态不得仅凭 fixture 提升为 accepted。
- JCSA/Racing Victoria 可在每源列表 1 次、详情最多 2 次、透明 UA、零业务写入的显式命令下
  做一次补救后技术复测；permission 仍为 unknown，故即使 technical accepted 也继续
  production blocked。

## 5. 归属设计

### 5.1 规则词表

`news_attribution.py` 的地区排序扩展为：

`日本 -> 中国香港 -> 英国 -> 爱尔兰 -> 法国 -> 美国 -> 加拿大 -> 阿联酋 -> 沙特 -> 澳大利亚 -> 其他`

这只用于稳定显示和去重，不表示优先权。

新增强事件/赛场信号：

- 爱尔兰：Curragh、Leopardstown、Fairyhouse、Naas、Punchestown、Galway、Irish Derby、
  Irish Champion Stakes、HRI
- 加拿大：Woodbine、Fort Erie、King's Plate、Woodbine Mile、Ontario Racing
- 阿联酋：Meydan、Dubai World Cup、Dubai Racing Club、Emirates Racing Authority、
  Jebel Ali、Abu Dhabi、Al Ain
- 沙特：Saudi Cup、Riyadh、King Abdulaziz Racecourse、JCSA
- 澳大利亚：Flemington、Randwick、Rosehill、Caulfield、Moonee Valley、Melbourne Cup、
  The Everest、Racing Victoria

普通国家形容词只作上下文；赛事、赛场和明确机构才是强事件中心。`Dubai`、`Saudi Cup`、
`Woodbine` 等从 `OUT_OF_SCOPE_TITLE_KEYWORDS` 移入正式映射。临时
`IRELAND_KEYWORDS -> related UK + ireland tag` 逻辑停止用于新归属，但不删除旧标签。

### 5.2 主地区与关联地区候选

继续复用单主地区模型：

1. 标题中唯一强赛事/赛场决定主地区。
2. 明确标题主体可以在已审核的少数模式下高于赛事地。
3. 本地来源没有强外国赛事时回退来源地区。
4. 本地来源报道强外国赛事时，外国赛事为主地区；来源地区只有在来源本身代表该地行业，
   或标题/导语存在该地核心对象时才成为关联地区。
5. 多个强赛事中心冲突进入 `needs_review`。

必须覆盖两组重点边界：

- Sporting Life 报道 Irish Derby：爱尔兰主地区，而非英国。
- HRI 报道爱尔兰马参加 Cheltenham：英国主地区、爱尔兰关联地区。
- TDN 报道 Woodbine：加拿大主地区，而非美国。
- Woodbine 报道加拿大马参加 Breeders' Cup：美国主地区、加拿大关联地区。

阿联酋/沙特同理独立判断。不存在 `middle_east` 自动关联。

### 5.3 全局 mode off 时的真实入库口径

当前生产 `MULTIREGION_ATTRIBUTION_MODE=off`，本 change 不开启全局 `shadow/enforce`。为避免
crawl-only 灰度静默误归属，新增默认关闭的 source-scoped 候选路径：

- `NEW_REGION_NEWS_ATTRIBUTION_CANDIDATES_ENABLED=false`
- `NEW_REGION_NEWS_ATTRIBUTION_CANDIDATE_SOURCES=`（source key allowlist）

只有开关开启且来源显式允许时，`upsert_article_from_draft()` 后才运行推断并把结果写入
`attribution_summary.review_candidate`、规则版本、置信度和冲突原因；它不修改
`NewsArticle.racing_region` 或 `NewsArticleRelatedRegion`。文章保留来源地区，并写
`region_review_required` 硬门禁/人工审核状态。

运营人员确认候选后，通过现有编辑入口明确保存主/关联地区并设置 `attribution_locked=true`。
只有锁定完成且其他发布门禁通过的文章才可公开/推 QQ。候选开关不能提升全局 mode，也不影响
allowlist 外旧来源。未来若要自动应用新地区归属，另行取得新规则 Gold/Shadow 资格。

端到端测试必须使用真实计划 settings：全局 mode off、候选开关开启、仅新 source allowlist，
覆盖 adapter draft → upsert → candidate 持久化 → 发布/QQ 阻断 → 人工确认锁定。

### 5.4 规则版本和历史数据

规则版本从 `multiregion-v3` 前进到新版本。现有 Gold Set 中 `other` 曾代表澳洲、爱尔兰、
沙特、迪拜等内容，因此现有五区/other 指标不能直接作为新版本资格。

实施只让新抓取文章走新规则。另提供只读候选导出：

- 旧 `tags_json` 包含 `ireland`；
- 旧主/关联地区为 `other` 且标题命中新五区；
- 现有英国/美国文章中标题命中爱尔兰/加拿大强赛事。

导出只用于后续人工 review，不在本 change 执行 commit。

## 6. 抓取、幂等和失败

数据流保持：

`ProductionWindow/source poll -> CrawlJob -> adapter list -> detail -> canonical draft -> upsert -> translate/review`

- 同源文章唯一性继续使用 `source_site + source_article_id`。
- canonical URL 去除 tracking query/fragment，source ID 由稳定站点 ID 或 canonical URL hash 生成。
- 本专项只保证同一 `source_site` 内 canonical URL/query/fragment 稳定去重。不同
  `source_site` 的跨来源身份合并、canonical owner 和并发仲裁不在本专项；既有 TDN 特例保持
  原状，后续如需通用跨来源合并另起设计。
- 单篇详情失败继续处理；整轮零可解析详情时任务失败。
- 对五个新 adapter，HTTP 200 但零列表项抛出稳定 `empty_listing`，CrawlJob 失败并进入
  parse/empty backoff；全部详情失败使用 `all_details_failed`；全部重复仍成功且
  `new_count=0/duplicates>0`。
- 403/429/验证码进入现有保守 backoff，不切换代理绕过。
- 网络请求不放在数据库事务内；每个来源沿用运行中检查和每轮上限。

## 7. UI、生产窗口和 QQ

运营后台的来源/地区生产视图使用 `NEWS_PRODUCTION_REGIONS`，显示五个新地区。公共入口拆为：

- `PUBLIC_NEWS_REGION_TABS` / `_resolve_public_news_region()`：旧五区 + 新五区；
- `PUBLIC_HORSE_REGION_TABS` / `_resolve_public_horse_region()`：保持现有马匹支持地区；
- 赛事日历继续使用 `RACE_DATA_REGIONS`。

新闻首页保留现有主地区入口，并增加可访问的“更多地区”选择；其中阿联酋、沙特显示在“中东”
视觉分组下，query 参数仍分别为 `united_arab_emirates`、`saudi_arabia`。马匹页对新五区参数
按无效筛选处理且不展示空 tab。移动端必须可键盘/触控操作且不产生页面级横向溢出。

生产窗口、自动发布和 QQ 都只消费显式 allowlist：

- 迁移/同步后新来源关闭；
- crawl 灰度先开单源、单地区；
- publish/QQ 继续关闭；
- 新地区至少完成抓取和翻译质量抽检后才讨论发布；
- 既有群空 `allowed_regions` 继续只允许日本。

## 8. 可观测性

每个新地区至少输出：

- 来源总数、启用数、生产批准数、paused/backoff；
- 最近抓取状态、HTTP/错误分类；
- 新增、重复、历史过滤、缺失时间、详情失败；
- 待翻译、翻译失败、人工审核、门禁原因、公开数；
- QQ delivery；
- 归属 `applied/fallback/needs_review` 和跨地区例子。
- probe 的 technical/permission/effective 三轴状态、版本、审核时间和 artifact SHA。

发布时间 evidence 必须从 adapter metadata 持久化到 `NewsArticle.published_at_evidence` 和
`NewsSnapshot.snapshot_metadata`，至少含 raw、timezone、precision、parser_version、
verified。详情缺时间也计入 `source_summary.published_at_missing`；后续重复抓取的未验证/
低精度时间不得覆盖已有 verified 时间。

真实探测 artifact 保存探测时间、URL、HTTP、解析器版本、条款结论和最小样本摘要；不保存凭据，
不提交大段第三方正文。

## 9. 性能与安全

- 每源列表最多 20 条，probe 默认详情最多 2 条，生产初始每源每轮上限更保守。
- 新地区审计沿用有界 24 小时窗口和聚合查询，不为每地区/来源逐条 N+1。
- 新枚举不得让历史批次多出目标或让 race-live initializer 接受未注册地区。
- fixture 测试禁止真实网络；真实网络探测为独立手动验证。
- 所有新来源和发布能力默认关闭，生产动作需要最新代码 review 后的独立用户授权。

## 10. 部署与回滚

建议顺序：

1. 部署代码和 choice migration，所有新来源保持关闭。
2. 同步来源定义，确认五个来源均 `enabled=false/production_approved=false`。
3. 逐源执行只读 probe；条款和技术均通过后才允许候选灰度。
4. 每次只启用一个来源的 crawl，publish/QQ 关闭，观察至少多个有效窗口。
5. 每地区完成新增、时间、正文、翻译和归属抽检后，再单独评估发布。

回滚优先级：

1. 取消 `production_approved` 并停用问题来源；
2. 从 crawl allowlist 移除对应地区/来源；
3. 保留已入库文章和来源快照供审计，不删除；
4. 若必须回滚代码，先确认数据库中没有旧应用无法正确展示/编辑的新地区记录；否则保持前向兼容
   代码，只关闭行为开关。

本 change 不含实际部署。

## 11. 当前外部证据

2026-07-19 使用现有客户端固定 User-Agent 对五个候选入口执行只读 GET，均返回 HTTP 200：

- HRI：约 80 KB HTML
- Woodbine：约 470 KB HTML
- Emirates Racing Authority：约 201 KB HTML
- JCSA：约 68 KB HTML
- Racing Victoria：约 62 KB HTML

这些数字只作为入口连通性基线，不是 selector 或许可结论。

随后的显式 probe 使用每源列表 1 次、详情最多 2 次，并在迁移后的仓库外临时 SQLite 中只读
执行重复计数；五源均 HTTP 200，但技术状态全部 `deferred`：

- HRI：6 条列表，2 个详情均因非 ISO 可见日期成为 `missing_published_at`。
- Woodbine：错误匹配 `/news/` 根入口为唯一“文章”，详情缺时间。
- ERA：1 条真实详情，JSON-LD 有时间但解析器未读取。
- JCSA：旧媒体工具入口 `empty_sample`；浏览器验证正确 HTML 片段接口返回 12 条。
- Racing Victoria：静态新闻页 `empty_sample`；浏览器验证动态文章可见，公开 sitemap
  含 338 个 `/news/` URL，可作为不依赖前端凭据的列表发现入口。

首轮 probe artifact SHA-256 分别为：

- HRI：`69104fdd495e4b3865dd8aede081ad2cfb0110b8bc8530199d7d96a6caac6daa`
- Woodbine：`577bbe62adb9b34321090206184f5177f9d330ad752becaa3909154d99ddccd9`
- ERA：`21210deaddfc4158df8d864b645fe9ac0e4dda9b46d4ebbed448efc3aa4afb04`
- JCSA：`e934ee1e07a082333bcf51b1307b276bcb3391ac6f2dd17f487ffead814204db`
- Racing Victoria：`0a0cc37c856aba150c6088cf7e3dd803686b4ffffadd5f16b53539e58958006b`

robots 当前未禁止普通新闻路径，但不等于再利用许可；HRI/Woodbine/ERA 为 `blocked`，
JCSA/Racing Victoria 为 `unknown`。当前没有来源可成为 `eligible`。

## 12. 补救实现与第二次受控 proof

补救实现只为五个新 adapter 使用透明
`umanewsbot/1.0 (+https://umafans.run)` User-Agent；有界 helper 仅新增逐请求
`user_agent`、`accepted_content_types`，未改变旧 `DEFAULT_HEADERS`、`get_bytes()` 或旧
adapter。Racing Victoria 只有固定 sitemap listing 可接受 XML，所有详情与其他来源仍只接受
HTML。非 `200` 使用不携带正文或请求头的结构化异常保留 `status_code/final_url`，使
adapter、probe、crawl、失败 ProductionWindow/CrawlJob 和 `360` 分钟 blocked backoff 可
保留精确 `403/429` 诊断。

五站真实解析实现：

- HRI 只接受 `/news/details/`，URL 先 HTML unescape 再安全 percent-encode，支持 Dublin
  英文长日期；
- Woodbine 只接受 `/woodbine-news/`，排除 `/news/`、`/blog/`，读取
  `article:published_time`/JSON-LD，正文限定 `.entry-content`；
- ERA 读取 JSON-LD 或可见英文长日期，正文限定官方 article body；
- JCSA listing 使用 `/api/news/en/{offset}/12`，详情限定 `h1`、`.content-area` 和来源专属
  `.text-black-body.font-inter.text-small-body` 日期；
- Racing Victoria listing 使用 sitemap，严格接受 `/news/YYYY/MM/DD/slug`，详情只从
  `script#__NEXT_DATA__` 的 Sitecore route 读取 `Title/ArticleDate` 与
  `headless-main` 的 `RichText`，排除 footer 和 `DCAArticleList`。

补救在线复测仍遵守预先声明预算，只请求 permission `unknown` 的两源：

- JCSA：listing HTTP `200`、`12` 条；当时抽样当前详情因 selector 尚未对齐而
  `missing_published_at`，technical `deferred`，artifact
  `0244333e5c84ea9da8d55e604cae6ea9a1c3c1fde79186da3615e0177ed753ca`。剩余一次详情预算
  保存同一当前页面后，离线修复可解析标题、`724` 字正文和
  `2026-03-22T14:00:00Z`，但没有再次联网生成 accepted artifact。
- Racing Victoria：sitemap HTTP `200`；当时 regex 使用错误的连字符日期，list count
  `0`、technical `deferred`，artifact
  `d35b541c698a94aba8e5b4979d8f0d3a64eba81c306b50c28bce5ce1fa304c9f`。已有保存详情 URL
  证明真实路径为 `/news/YYYY/MM/DD/slug`，已离线修复并进入严格 fixture；列表预算用完，
  未重复联网。

HRI、Woodbine、ERA 因 permission `blocked` 未再次联网。由此，当前实现具备离线解析与错误
诊断证据，但五来源最终 effective 状态仍全部为 `production_blocked`；技术状态不得凭 fixture
从 deferred 提升为 accepted。

## 13. 第二批来源池与 date-only 候选设计

### 13.1 最小代码边界

本轮不为每个调研入口新增 `SourceSite`、migration 或生产 adapter。新的运行时行为只有：

1. 在国际新闻候选入库前读取 `published_at_evidence.precision/timezone`；
2. 对 `precision=date` 执行来源当地日期差规则；
3. 在 crawl/probe 摘要中记录候选或历史原因；
4. 补齐 `Irish Oaks`、`Woodbine Oaks` 等经真实样本暴露的地区强信号。

来源调研矩阵是 durable 证据，不会把 HTTP 200 或 robots allow 转换成许可 approved。
blocked 入口只保留 URL、条款结论和既有最小技术证据，不新增联网测试。

### 13.2 date-only 判定

候选分类放在独立 integration service，输入为：

- `published_at`
- `published_at_evidence`
- 本轮固定 `crawled_at`

算法先验证证据合同，再做日期计算：

```text
if published_at is missing or published_at/crawled_at is naive:
    return unresolved
if evidence.verified is not true or draft.published_at_verified is not true:
    return unresolved
if precision in {"minute", "second"}:
    return precise_time_not_applicable
if precision != "date":
    return unresolved
zone = ZoneInfo(evidence.timezone)  # invalid => fail closed
published_local_date = published_at.astimezone(zone).date()
crawled_local_date = crawled_at.astimezone(zone).date()
date_difference_days = abs(crawled_local_date - published_local_date).days
if date_difference_days <= 1:
    return candidate_date_within_one_day
return historical_date_outside_one_day
```

使用绝对日差是为了严格执行用户给定的“差值不大于 1 天”，同时容纳 UTC/来源当地日期边界。
未来日期超过 1 天同样不进入候选；不另行猜测发布方时钟错误。`published_at` 的当地 12:00
只是 date-only 规范化值，不参与小时级年龄计算。

`_crawl_international_source()` 的顺序固定为：

```text
normalize draft
-> preview_content_scoped_region(draft title + first 400 body chars)
-> Ireland/Canada target 才执行 freshness
-> historical/unresolved 在 upsert 前结束
-> candidate/普通 UK-US 稿进入 upsert
-> attribution 复用同一 preview result 保存 review_candidate
```

`preview_content_scoped_region()` 是无数据库写入纯函数，复用 `news_attribution` 的同一组
`EVENT_REGION_KEYWORDS`、边界匹配器、稳定排序和冲突规则，返回不可变
`AttributionPreview(target_region, confidence, needs_review, evidence)`。crawl 在任何 upsert
前只调用一次；同一对象同时决定 target freshness scope，并通过显式
`attribution_preview=` 参数传给 `upsert_article_from_draft()` 和正式 attribution。正式路径
不得从 draft metadata 再解析或重新计算另一个 target。其他写入入口若启用 content-scoped
候选，也必须在其最外层副作用前调用同一函数一次；缺 preview 时以
`attribution_preview_required` fail closed。

freshness 分类器的分支为：

- `candidate_date_within_one_day`：正常进入既有 upsert/归属/翻译编排；
- `historical_date_outside_one_day`：不写文章，追加有界 skip reason，并计入
  `source_summary.historical_filtered`；
- `precise_time_not_applicable`：完全保持 verified 精确时间文章既有行为；
- `unresolved`：缺时间、precision 缺失/未知、任一 verified 标志不为真、naive datetime 或
  无效时区；不得进入本轮新五地区候选，单篇失败并继续本轮其他文章。

该严格证据门禁只用于 preview 明确判定为 Ireland/Canada 的本专项候选：如果复用来源缺少
可信时间，文章不因 listing 临时写入的 crawl time 而进入候选。preview 为普通 UK/US 或冲突
未决的文章不应用本增量 freshness，保持旧国际文章既有行为，避免把来源扩展隐式变成全量
历史清理。

probe 不写业务表，但对每个样本输出相同判定、日差、来源时区和固定 `crawled_at`，使实抓结果
可以复跑。一次 probe/crawl 只生成一个 aware `crawled_at`，所有样本共享。候选的
`decision/crawled_at/source_timezone/published_local_date/crawled_local_date/
date_difference_days` 写回 draft metadata，沿用 ingestion 写入 article translation metadata
与 snapshot metadata；historical/unresolved 进入有界 CrawlJob 和 ProductionWindow
`source_summary`，不创建 `NewsArticle`。

### 13.3 复用来源的地区归属

爱尔兰、加拿大不建立“复制版”英国/美国来源。现有 adapter 产出的文章继续保留 canonical
source site，归属服务根据标题和导语中的强事件/赛场信号生成独立地区候选：

- Ireland：`Irish Oaks`、`Irish Derby`、Curragh、Leopardstown 等；
- Canada：`Woodbine Oaks`、Woodbine、Ontario、King's Plate 等。

来源默认地区只作为弱回退，不压过强事件地区。TDN 等 canonical 来源若条款 blocked，不能通过
新增 Ireland/Canada wrapper 绕过；本轮只使用此前允许的最小元数据证据，不抓取其全文用于
翻译。

### 13.4 canonical permission 门禁

新增单一 permission resolver，以 adapter 的 `canonical_source_site`（不存在时使用
`source_site`）为键，返回 `approved/unknown/blocked/expired`。wrapper 不可覆盖 canonical
结论；TDN、TDN France 与任何后续地区关键词包装器均解析为 canonical TDN 的 `blocked`。

- probe 在 `fetch_listing()` 前检查；blocked/expired 返回结构化
  `permission_blocked_preflight`，
  list/detail 调用均为 0。unknown 只有显式技术 probe 参数才可联网，默认矩阵不包含。
- 显式 `crawl_news_source_task` 可以先创建零请求审计 `CrawlJob`，但无论 production flag
  值为何，都必须在调用任何 adapter 网络方法前完成 managed canonical preflight；不满足则
  CrawlJob 失败并记录 `permission_blocked_preflight`。
- 既有自动 polling 改为调用独立的 scheduled task entry。只有该入口受默认关闭的 production
  enforcement flag 控制；flag 关闭时保持变更前调度行为，flag 开启时 managed canonical 才
  额外要求 permission `approved`。调用 origin 由两个不同 task 函数固定，不能使用外部可传的
  `origin/bypass` 参数。
- 通用 enabled-source polling 只选择 `production_approved=true`；不能靠误开 `enabled`
  绕过生产批准。
- permission 状态是运行时常量/registry，不只存在于文档或 notes；所有新五地区第一批来源及
  TDN canonical 状态必须显式登记。

这一门禁不会授予任何来源新许可。显式登记为 `unknown/blocked/expired` 的来源严格执行上述
规则。本 change 的 `MANAGED_PERMISSION_SOURCES` 固定为五个首批 adapter canonical key 与
TDN canonical key；别名只映射到 canonical，不扩大集合。为避免本增量静默停止既有生产抓取，
registry 未登记且不属于该集合的 legacy canonical 来源进入兼容状态
`legacy_permission_unregistered`：

- dispatcher 不为它新增任何 permission 条件，完全沿用变更前的选择/direct-crawl 代码路径；
- 每次选择、probe 和 crawl 输出审计 reason，不能显示为 permission `approved/eligible`；
- 不得用于本轮 Ireland/Canada content-scoped 候选或新五地区生产；
- 后续由独立“全来源许可治理”专项逐源补批准依据；本 change 不猜测历史授权。

自动 scheduled crawl enforcement 使用独立默认关闭配置
`NEWS_SOURCE_PERMISSION_PREFLIGHT_ENFORCEMENT_ENABLED=false`。probe/本轮隔离 research
与 public/direct task 始终执行 resolver；只有自动 scheduled task 在 flag 关闭时保留既有
managed source 行为，flag 打开时也只影响 `MANAGED_PERMISSION_SOURCES`。现有 enabled 且
production-approved 国际源在变更前后的自动选择集合必须完全相等，TDN 可能的差异单独列出，
不得混进 registry completeness。TDN 是当前唯一计划中的 legacy 生产影响候选；开启 flag 前
必须核对 TDN、TDN France、TDN broad 的实时选择状态并取得精确停抓授权，关闭 flag 即回滚。

后续若取得书面许可，须独立更新证据、registry 状态和审核。

### 13.5 中东与澳洲来源调研结论

- UAE：ERA、Dubai Racing Club、Gulf News、The National 当前均为 permission blocked；
  Godolphin/NMO-WAM 只保留低频 discovery 候选，未找到可批准的稳定列表和再利用授权。
- Saudi：JCSA permission unknown 且季节性；SPA 与 Arab News blocked。只在赛季窗口提高
  JCSA/全球发现频率，不把淡季零稿当解析故障。
- Australia：Racing Victoria permission unknown；Racing.com、Just Horse Racing、
  Breednet、VRC 均被官方条款限制，Racing and Sports、Racenet、Punters、Racing Queensland
  当前透明请求 403。Racing Australia 官方 media releases 可达但低频且主要为 PDF，只作
  官方事实补充，不在本轮引入 PDF parser。

详细逐源状态、入口、时间精度与 no-go 原因见 `source_research.md`。

### 13.6 隔离实抓和翻译

- 使用仓库外新 SQLite，迁移到当前 HEAD，不连接生产。
- blocked 来源零请求；unknown 来源只有显式 technical-probe 模式可按每源列表 1 次、详情
  最多 2 次在内存解析，不创建业务记录。
- 只有 permission `approved`、freshness 合格且地区归属明确的真实文章才可写入隔离库并
  运行外部全文翻译；若没有 eligible 候选，如实报告“无可合法运行的真实候选”。
- 翻译任务机械链路改用项目自有合成文本或已保存的最小测试 fixture 验证；必须将
  fixture/dummy、真实 provider 与真实外部新闻翻译分开报告，fixture 结果不得冒充新闻产出。
- 所有来源保持 `enabled=false/production_approved=false`，公开、QQ、通知均为 0。

### 13.7 全历史/全未决批次语义

- 列表非空且详情均成功解析，但全部为 historical：CrawlJob 成功、`new=0`，
  `historical_filtered>0`，不是 `all_details_failed`。
- 列表非空但全部时间 evidence 为 unresolved：CrawlJob 失败并使用稳定
  `all_candidates_unresolved` 原因；不得误报成功零新增。
- `crawl_news_source_task` 成功窗口保存完整 `source_summary`；失败窗口保存
  `source_summary` 与稳定 error category，供运营态复核。

## 14. 方案审核修订

### 14.1 canonical permission preflight

新增 `server/stable/services/source_permissions.py`，维护不可由 adapter/wrapper 自行放宽的
canonical registry。每条记录至少包含：

- `canonical_source_site`
- `status=approved|unknown|blocked|expired`
- `allowed_hosts`
- `evidence_url`
- `reviewed_at`
- `notes`

resolver 先读取 `adapter.canonical_source_site or adapter.source_site`，再校验声明 host 是否属于
canonical record。adapter class 上的旧 `automation_permission_status` 只保留兼容展示，最终
状态以 registry 为准；wrapper 不得覆盖 canonical 状态。

调用顺序固定为：

```text
instantiate adapter（不得联网）
-> resolve canonical permission
-> blocked: return/raise permission_blocked_preflight, request_count=0
-> unknown: require explicit research mode + attached request budget
-> approved: continue existing dispatcher
-> unregistered legacy: do not add a permission predicate; continue the exact pre-change dispatcher
-> fetch listing/detail
```

`probe_international_news_sources`、本轮隔离 runner 和 public
`crawl_news_source_task()` 永远执行同一 resolver。自动 production polling 不再复用 public
task，而是调用参数签名不暴露 bypass/origin 的 `crawl_scheduled_news_source_task()`；该 task
内部固定传入不可由 Celery 参数覆盖的 scheduled policy。仅 scheduled policy 在
`NEWS_SOURCE_PERMISSION_PREFLIGHT_ENFORCEMENT_ENABLED=false` 时保持旧行为，flag 为 true
才对 managed set 强制 preflight。TDN、TDN France、TDN broad 解析到同一个 TDN blocked
record；HRI、Woodbine、ERA 同样 blocked；JCSA、Racing Victoria 为 unknown。未登记的新五
地区或 wrapper fail closed 为 unknown。managed set 之外返回
`legacy_permission_unregistered`，不能显示为 eligible，但不得改变既有 dispatcher 结果。

registry completeness 是两类不同断言：

1. managed canonical 集合必须与预先声明常量完全相等，所有别名都解析到其中一项；
2. 变更前 enabled + production-approved 国际来源快照与 flag 关闭后的自动 scheduled 选择
   集合完全相等；public/direct task 的 blocked 零请求不纳入此兼容豁免。

flag 打开时允许的唯一预期 legacy 差异是经另行授权的 TDN canonical 家族；本轮 flag 保持关闭。

### 14.2 可注入请求预算

新增纯内存 `SourceRequestBudget`，按单个 source probe 隔离计数：

- blocked：listing `0`、detail `0`
- unknown research：listing `1`、detail `2`
- 每次 HTTP transport GET 前 `consume(kind, url)`；超过预算在请求前抛
  `source_request_budget_exhausted`
- ledger 记录 kind、canonical host、URL、attempt ordinal、结果状态；不记录正文、请求头或
  cookie

listing `1`、detail `2` 指实际 `session.get()` 次数。可选
`before_transport_get(kind, url)` callback 下沉到 `_bounded_html()` 的 redirect loop 内，
紧贴每次 `session.get()` 之前执行；首跳、redirect、失败 redirect 和任何 helper 内重试都消费
同类预算。因而 listing 首跳若重定向，第二跳在网络前即预算耗尽并停止，这是预期 fail-closed
行为，不把 redirect 当免费请求。

只有实现 `supports_research_request_budget=True` 且所有网络入口都把 callback 传入 transport
loop 的 adapter 才能以 unknown 状态联网。本轮只有 `TrustedLocalTimeNewsAdapter` 路径满足；
JCSA/Racing Victoria 可显式 probe。普通 Simple adapter、TDN 多查询 adapter 和未来未接入
transport hook 的 unknown 来源一律 `research_budget_unsupported`、零请求。

因此 TDN broad 的多查询不会消耗“隐藏请求”：它在 permission preflight 已 blocked；若未来
许可改变，必须先把每个 query 子请求接入预算协议才允许 research probe。

### 14.3 content-scoped mode-off candidate

新增默认关闭配置：

- `MULTIREGION_CONTENT_SCOPED_CANDIDATES_ENABLED=false`
- `MULTIREGION_CONTENT_SCOPED_CANDIDATE_SOURCES=[]`

source allowlist 使用 canonical `SourceSite`，不使用 wrapper key。`apply_article_attribution()`
在 mode off 下保持既有 source-scoped 路径，同时增加严格 content-scoped 分支：

1. canonical source 在 allowlist；
2. 使用 upsert 前 `preview_content_scoped_region()` 的同一 result，目标为 Ireland 或 Canada；
3. 证据来自标题/导语的 event/location 强信号，状态非 `needs_review`，confidence 达到既有
   high 门槛；
4. 满足时只保存 `review_candidate`、设置人工地区审核门禁，不写主/关联地区；
5. 不满足时不保存候选、不增加门禁，保持普通 UK/US 文章现状。

适配器和调度仍只抓 canonical 来源一次。upsert identity 继续使用 canonical
`source_site + source_article_id`；重复发现只新增 snapshot/last_seen，不新增第二篇文章。
content-scoped allowlist 命中时，upsert 必须收到显式不可变 preview result；缺失即
`attribution_preview_required`，不得在 upsert 后补算。未命中该专项路径的 legacy upsert
不新增此参数要求。

### 14.4 freshness 固定摘要

`source_summary` 增加固定字段：

- `candidate_date_within_one_day`
- `historical_date_outside_one_day`
- `precise_time_not_applicable`
- `published_at_missing`
- `invalid_published_timezone`
- `freshness_unresolved`

混合批次、全历史批次仍可成功结束；列表存在但全部 freshness 未决时使用稳定
`all_candidates_unresolved`，只有实际详情解析全部异常才使用 `all_details_failed`。历史稿在
upsert 之前结束，不产生 NewsSnapshot、术语发现、翻译、ranked revival 或 QQ 副作用。

### 14.5 Canadian Thoroughbred 与旧 TDN 证据

Canadian Thoroughbred 本轮已经取得一次透明请求最小证据：列表 200、`/horse-news/` 详情
200、`<time datetime=2026-07-17>`、正文 selector 可见。为避免把 unknown 约定误作硬预算，
方案审核后不再联网、不新增 adapter；仅用不含第三方正文的最小 synthetic fixture 验证
date-only 规则。后续若要做可复跑 live probe，必须另行实现 research-only collector 并通过
canonical permission/budget 门禁。

第一批 TDN SQLite 是 blocked 结论前的历史探测。它不作为第二批验收输入；实施阶段只将整个
数据库移动到仓库外 mode `0700/0600` quarantine，不读取或重新处理正文。新的第二批 SQLite
从空库开始，并断言 blocked source 的 NewsArticle、TranslationRun 与网络请求均为 0。

## 15. 内部使用与多来源第三批设计

### 15.1 访问控制

新增 `stable.middleware.InternalSiteOnlyMiddleware`，放在
`AuthenticationMiddleware` 之后、业务 view 之前。配置：

```text
SITE_INTERNAL_ONLY_ENABLED=true
SITE_INTERNAL_ONLY_EXEMPT_PATHS=/admin/login/,/django-admin/login/,/healthz/,/robots.txt
SITE_INTERNAL_ONLY_TRUSTED_TLS_TERMINATION=false
NEWS_EXTERNAL_AI_PROCESSING_ENABLED=false
```

中间件按顺序处理：

1. 配置关闭时保持旧行为；
2. 已认证用户放行；
3. 精确例外路径、静态前缀和 admin 登录相关路径放行；
4. `/api/` 返回 `401 {"detail": "authentication_required"}`；
5. 其他请求使用 Django login redirect，`next` 只保存站内 path/query。

`robots.txt` 是独立极小 view：内部模式返回 `User-agent: *\nDisallow: /\n`。sitemap、新闻、
赛事和马匹公开 view 不再各自重复鉴权，由中间件统一保护；原有 API 上的 `login_required`
继续保留作为纵深防御。`/healthz/` 必须保持无认证 JSON 200。

媒体也属于内部边界：

- local backend：删除 Nginx `/media/` 公开 `alias`，改为认证 view 校验 session 和规范化相对
  path 后返回 `X-Accel-Redirect` 到仅 Nginx internal 可达的 `/protected-media/`；开发环境
  使用 `FileResponse`，两条路径都拒绝 `..`、symlink 逃逸和目录请求。
- OSS backend：只有 `OSS_PRIVATE_MEDIA_ENABLED=true`、private bucket 和短期签名 URL helper
  都通过启动预检时允许；否则 `SITE_INTERNAL_ONLY_ENABLED=true` 与 OSS 组合 fail closed。
- 第三批 adapter 不下载媒体，因此该路径只负责保护既有站内媒体，不扩大复制范围。

生产 rollout 的前置条件是 HTTPS：当前 `deploy/nginx/nginx.conf` 的 HTTP-only 入口不能用于
内部登录验收。`DEBUG=false` 时 session/CSRF secure cookies 必须同时开启；传输层只接受
direct `SECURE_SSL_REDIRECT=true`，或显式开启
`SITE_INTERNAL_ONLY_TRUSTED_TLS_TERMINATION` 且提供合法
`SECURE_PROXY_SSL_HEADER=(HTTP_*, https)`。只打开 trusted flag、只配置 proxy header 或关闭
secure cookies 均 fail closed。最终还必须证明登录、CSRF、media 和 `/healthz/`。

### 15.2 外部分发硬门

新增纯函数 `external_news_distribution_blocker()` 和
`sanitize_internal_ops_notification()`。以下入口都必须在副作用前调用：

- `qq_auto_push` eligibility、delivery 创建、URL check、单篇 task、窗口 task；
- `stable.services.pushing` 的旧手动 PushLog/OneBot 路径，且阻断点早于 PushLog 创建；
- `notifications`、`translation_recovery`、`ops_notifications` 中携带文章上下文的邮件/QQ。

全局内部模式对正文分发固定返回 `internal_only_distribution_blocked`。此外，来源级
`usage_scope=internal_only` / `public_publish_allowed=false` 必须独立生效：即使全局登录墙
关闭，公开 queryset、详情和 QQ 仍用文章级 blocker 排除该稿件。运维通知只能由 sanitizer
生成字段白名单 payload：任务名、稳定错误分类、安全计数、时间和内部整数 ID；输入中出现
原文标题、正文、译文、摘要或来源 URL 时丢弃对应字段，若剩余信息不足则不发送。文章级翻译
失败通知只允许 `article_id`，不恢复来源 URL。不删除历史 PushLog/delivery，不把历史成功
记录改写失败。

`WorkflowStatus.PUBLISHED` 保留，语义调整为内部内容状态；匿名中间件保证已有
`published_to_web_at` 不能公开读取。自动发布本身不自动产生外部副作用。后续若要恢复公开
访问，必须另起任务同时评估现有 PUBLISHED 存量，不允许只关中间件。

### 15.3 canonical 来源准入

`SourcePermissionRecord` 兼容保留类名，字段改为：

```python
technical_access: Literal["accepted", "blocked"]
usage_scope: Literal["internal_only"]
public_publish_allowed: bool
terms_risk: str
allowed_hosts: tuple[str, ...]
evidence_url: str
reviewed_at: str
```

旧 `status/reason/allowed` 决策输出保留兼容键，但 `allowed` 仅表示能否内部联网：

- accepted -> `allowed=True / reason=internal_only_technical_access`
- blocked -> `allowed=False / reason=technical_access_blocked`
- host mismatch -> `allowed=False / reason=technical_host_mismatch`
- 未登记 legacy -> 沿用旧 dispatcher，同时输出 `legacy_permission_unregistered`

`production_approved` 继续控制是否允许常态调度。它不再被界面解释为第三方授权。所有新源
仍同步为 false，必须由后续内部灰度显式开启。

### 15.4 adapter 分层

新增 `TrustedRssNewsAdapter`，复用现有有界 HTTPS transport 和
`TrustedLocalTimeNewsAdapter` 的详情/evidence 逻辑：

- 使用 stdlib XML/BeautifulSoup XML 解析 RSS 2.0 与 Atom；
- feed 最多保留 20 条，按 canonical URL/GUID 去重；
- RFC 2822、ISO 8601 时间必须转 UTC，并按原值粒度标记现有 classifier 已接受的
  `precision=minute` 或 `precision=second`；不得新增 `datetime`；
- feed 没有精确时间时由详情提供 date-only evidence；两者都缺失则 fail closed；
- feed 与详情 host 分别使用静态 allowlist，redirect 每跳重新校验；
- 不读取 enclosure/media，不创建图片 draft。

本批新增 adapter：

| adapter key | listing |
| --- | --- |
| `rte_racing` | `https://www.rte.ie/feeds/rss/?index=/sport/racing/` |
| `irishracing_news` | `https://www.irishracing.com/news` |
| `canadian_thoroughbred` | `https://canadianthoroughbred.com/news/` |
| `assiniboia_downs_news` | `https://asdowns.com/feed/` |
| `dubai_racing_club` | `https://dubairacingclub.com/feed/` |
| `the_national_racing` | `https://www.thenationalnews.com/sport/horse-racing/` |
| `spa_horse_racing` | `https://www.spa.gov.sa/en/search?search=horse%20racing` |
| `arab_news_racing` | `https://www.arabnews.com/tags/horse-racing` |
| `just_horse_racing` | `https://www.justhorseracing.com.au/feed` |
| `the_straight` | `https://thestraight.com.au/feed/` |
| `racing_nsw_news` | `https://www.racingnsw.com.au/feed/` |
| `tasracing_news` | `https://tasracing.com.au/news/rss.xml` |

HTML adapter 继续明确 selector 和路径 allowlist，不构建任意 URL 抓取器。Dubai Racing Club
优先 RSS，WP API 只作为同 canonical source 的备用 listing；不能在同一轮双抓产生重复正文。

逐源实现合同如下；fixture 基名与 adapter key 相同，分别使用
`<key>_listing.(xml|html)`、`<key>_detail.html`：

| SourceSite / adapter | listing 与 MIME | detail host/path | 标题/正文/时间 evidence 优先级 | 时区 / parser / interval | fallback |
| --- | --- | --- | --- | --- | --- |
| `rte_racing` | `www.rte.ie/feeds/rss/`；`application/rss+xml` | `www.rte.ie/sport/racing/YYYY/MMDD/<id>-<slug>/` | RSS title；详情 `og:title -> h1`、`JSON-LD articleBody -> article`；RSS `pubDate` 为 `second` | `Europe/Dublin` / `rte-racing-rss-v1` / 30m | 无 |
| `irishracing_news` | `www.irishracing.com/news`；HTML | 同 host `/news/<slug>/<numeric-id>` | 列表 `h4`；详情 `og:title -> h1`、`.news-story -> .news-content -> article`；列表日期组 + `.news-stamp` 组合为 `minute`，详情 meta 可覆盖 | `Europe/Dublin` / `irishracing-news-v1` / 20m | 无 |
| `canadian_thoroughbred` | `canadianthoroughbred.com/news/`；HTML | 同 host `/horse-news/<slug>/` | `og:title -> h1`、`.entry-content -> article`；`article:published_time -> JSON-LD datePublished -> time`，date-only 保留 `date` | `America/Toronto` / `canadian-thoroughbred-v1` / 60m | 无 |
| `assiniboia_downs_news` | `asdowns.com/feed/`；RSS/XML | 同 host `/<slug>/`，拒绝 author/tag/category/feed | RSS title；`og:title -> h1`、`.entry-content -> article`；RSS `pubDate` 为 `second` | `America/Winnipeg` / `assiniboia-rss-v1` / 120m | 无 |
| `dubai_racing_club` | `dubairacingclub.com/feed/`；RSS/XML | 同 host `/press-releases/<slug>/` | RSS title；`og:title -> h1`、`.entry-content -> article`；RSS `pubDate` 为 `second` | `Asia/Dubai` / `drc-rss-v1` / 120m | 默认 RSS；只有运营显式把 source listing strategy 切到 WP 时使用 `/wp-json/wp/v2/posts`，同一 CrawlJob 不自动双请求 |
| `the_national_racing` | `www.thenationalnews.com/sport/horse-racing/`；HTML | 同 host `/sport/horse-racing/<slug>/` | listing JSON/section anchors；详情 JSON-LD `headline/articleBody/datePublished`，再回退 `h1/article/meta`；精确值为 `minute/second` | `Asia/Dubai` / `the-national-racing-v1` / 60m | 无；列表超过 2 MiB 时技术 blocked，不改抓通用首页 |
| `spa_horse_racing` | `www.spa.gov.sa/en/search?search=horse%20racing`；HTML + `__NEXT_DATA__` | 同 host `/en/N<numeric-id>` | `__NEXT_DATA__` 搜索结果 title/url；详情 page payload `title/content/published_at`；仅 horse-racing 主题，精确值为 `minute/second` | `Asia/Riyadh` / `spa-horse-racing-v1` / 120m | 可人工把固定 hashtag `/en/news/hashtags/7727` 设为 listing；同一 job 只选一个 |
| `arab_news_racing` | `www.arabnews.com/tags/horse-racing`；HTML | 同 host `/node/<numeric-id>/sport` | listing `.view-content` 中 sport node；`og:title -> h1`、`.field-name-body -> article`；meta/JSON-LD date | `Asia/Riyadh` / `arab-news-racing-v1` / 120m | 无；非 `/sport` node 在详情前排除 |
| `just_horse_racing` | `www.justhorseracing.com.au/feed`；RSS/XML | 同 host `/news/australian-racing/<slug>/<numeric-id>` | RSS title；`og:title -> h1`、`.entry-content -> article`；RSS `pubDate` 为 `second` | `Australia/Melbourne` / `just-horse-racing-rss-v1` / 15m | 无；`/tips/` 和非 `/news/australian-racing/` 详情前排除 |
| `the_straight` | `thestraight.com.au/feed/`；RSS/XML | 同 host `/<slug>/` | RSS title；`og:title -> h1`、`.entry-content -> article`；RSS `pubDate` 为 `second` | `Australia/Sydney` / `the-straight-rss-v1` / 30m | 无；标题/分类命中 betting/prediction market 时排除 |
| `racing_nsw_news` | `www.racingnsw.com.au/feed/`；RSS/XML | 同 host `/news/<category>/<slug>/` | RSS title；`og:title -> h1`、`.entry-content -> article`；RSS `pubDate` 为 `second` | `Australia/Sydney` / `racing-nsw-rss-v1` / 15m | 无 |
| `tasracing_news` | `tasracing.com.au/news/rss.xml`；RSS/XML | 同 host `/news/<slug>` | RSS title/category；`og:title -> h1`、`.news-detail -> article`；RSS `pubDate` 为 `second` | `Australia/Hobart` / `tasracing-rss-v1` / 60m | 无；只有 category/title/body 强 thoroughbred 信号，harness/greyhound 排除 |

RSS `source_article_id` 优先使用 canonical same-host link；GUID 只在它是同一 canonical URL 时
使用，否则对 canonical link 计算稳定 hash。HTML source id 使用 canonical URL 的末段业务 ID
加 hash。所有 listing/detail 重定向逐跳校验表中 host；外部图片/resizer/CDN 链接不请求。

### 15.5 主题与地区过滤

过滤在详情请求前尽可能完成，在 upsert 前再次校验：

- Ireland：Curragh、Leopardstown、Punchestown、Galway、Irish Oaks/Derby 等；
- Canada：Woodbine、King's Plate、Fort Erie、Assiniboia、Hastings、Century Mile 等；
- UAE：Meydan、Dubai World Cup/Carnival、Jebel Ali、Abu Dhabi Turf Club、Al Ain 等；
- Saudi：Saudi Cup、JCSA、King Abdulaziz Racecourse、Riyadh、Neom/Red Sea Turf 等；
- Australia：Flemington、Randwick、Caulfield、Rosehill、Moonee Valley、各州官方来源等。

来源为地区本地官方/行业媒体时可使用来源地区 fallback；综合媒体必须有强信号。tips、odds、
betting、camel、show jumping、harness、greyhound 在 listing 阶段排除，并在正文 metadata
记录稳定 skip reason。

### 15.6 数据库与迁移

新增 migration 更新 `SourceSite` choices，不做数据迁移。最终集成已把本 change 的
`0047_alter_externaldataimporterror_racing_region_and_more.py` 与主线
`0047_race_live_public_beta_controls.py` 汇入
`0048_merge_20260719_2242.py`；第三批 choices 使用
`0049_alter_newsarticle_source_site_and_more.py`，没有复用冲突编号。最新 main 另有
`0048_raceeventrunner_external_runner_identity.py`；最终无操作
`0050_merge_20260720_0017.py` 同时依赖该 main migration 与功能 `0049`，成为唯一 leaf。

新来源仍使用现有 `NewsSource` 行，不新增表。内部访问和 registry 字段均为配置/代码层，
不对 `NewsArticle` 大表加列。

### 15.7 翻译处理

translation 与 rewrite task 在选择外部 provider 前共同调用
`external_ai_processing_allowed(provider)`，底层读取 `NEWS_EXTERNAL_AI_PROCESSING_ENABLED`：

- false：允许本地 provider；远程 translation 返回稳定 `external_translation_disabled`，
  文章保持待翻译；远程 rewrite 返回 `external_rewrite_disabled`，文章保持已有基准译文；
- true：沿用现有 translation/rewrite provider、model、重试和运行审计；
- dummy 仅用于测试，报告必须与真实 provider 分开。

检查必须位于 remote client 构造/调用和 task dispatch 副作用之前；自动化链在 translation
成功后也不得绕过 rewrite 门禁。retry selector 在外部 AI 禁用时必须在 claim 前跳过；
preclaimed 兼容调用要释放 article/run，batch skipped 不增加 translated count。该门禁不改变
采集成功状态，也不删除正文。

### 15.8 失败、容量和回滚

- 每源列表最多 1 个请求链、详情最多 20 条，沿用 host backoff；403/429/challenge 记录
  technical blocked，不能自动改 UA/代理重试。
- RSS 响应和 HTML 详情沿用 2 MiB 上限；Gulf News 等超大列表不在本批 adapter。
- 调度仍按 `NEWS_SOURCE_POLL_MAX_SOURCES` 和来源 interval 有界；所有第三批来源默认关闭。
- 回滚顺序：关闭具体 source -> 清空新地区/source allowlist -> 保持内部中间件开启 ->
  回滚 adapter 代码。不得以关闭内部中间件作为采集故障回滚手段。
- 双 `0047`、两个 `0048` 与 race-live 直接路径已在 final-integrated worktree 集成并完成
  SQLite 回归；发布前仍须完成 PostgreSQL 专项、最终精确版本复审和用户新授权。
