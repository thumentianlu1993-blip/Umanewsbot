# 新地区新闻抓取设计

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
