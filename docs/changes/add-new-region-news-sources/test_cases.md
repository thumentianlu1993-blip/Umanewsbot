# 新地区新闻抓取测试用例

## 文档状态

- 阶段：方案独立审核已 `VERDICT: APPROVED`；首次独立代码审核为
  `REVISE (2 P1 + 5 P2)`，七项 finding 已 RED/GREEN 闭环。同一 reviewer 对修复范围实质
  `APPROVED`，但 main 漂移使完整性门禁 `BLOCKED`；当前已重新集成
  `origin/main@a122ff6d…`，仍须复审最终精确版本。
- 当前验收入口：
  `/Users/mentianlu/Code/umanews/.worktrees/add-new-region-news-sources-release-candidate`
- 第三批 RED 基线：`62 tests / 74 expected failures / 0 errors`。
- review finding RED/GREEN：`7 failures / 0 errors -> 7/7`。
- 当前 GREEN：最新 release-candidate 离线组合 `214/214 OK`、live follow-up `10/10`；migration 无漂移、
  Django checks 通过。来源实现代理另报告 `202` 组合加 `1 skip`、translation recovery
  `22/22`。本文后续较早的 `175/175`、`69 OK`、`55/55`、`45/45`、`216` 等计数是不同集合
  的历史检查点，不代表当前摘要。
- RED 要求：新增运行时行为先观察因目标能力未实现而失败；本 change 的历史证据保留在本文
- CI 网络：禁止；适配器测试只使用最小 HTML/JSON fixture
- 真实网络：已在迁移后的仓库外 `/tmp` SQLite 用透明 bounded HTTP、每源 listing `1` /
  detail 最多 `2` 完成受控 probe；24 源为 `16 accepted / 8 blocked`。dummy 翻译编排已
  使用真实 RTÉ 正文通过，但真实中文远程 provider 仍未验证，不得把 dummy GREEN 冒充。

## 0. 第三轮 live evidence 验收

### TC-LIVE-001 探针环境与请求边界

- 首次空库 `no such table` 归类为探针环境问题，不归类为来源失败；应用 migration 后重跑。
- 使用仓库外 `/tmp` SQLite，不连接或写入生产；透明 bounded HTTP 保持 host、重定向、
  content type、大小与 timeout 合同。
- 每个来源 listing 最多 `1`、detail 最多 `2`；不通过扩大请求预算解释失败。

### TC-LIVE-002 24-source technical registry

- accepted 精确为 `16`：`rte_racing`、`irishracing_news`、`dubai_racing_club`、
  `jcsa_news`、`spa_horse_racing`、`racing_victoria_news`、`just_horse_racing`、
  `the_straight`、`racing_nsw_news`、`tasracing_news`、`tdn`、`bloodhorse`、
  `horse_racing_nation`、`sky_sports_racing`、`sporting_life`、`bha`。
- blocked 精确为 `8`：`hri_news`、`woodbine_news`、`canadian_thoroughbred`、
  `assiniboia_downs_news`、`emirates_racing_authority`、`the_national_racing`、
  `arab_news_racing`、`paulick_report`。
- 每条记录均断言 `usage_scope=internal_only`、`public_publish_allowed=false`；accepted
  不修改 `enabled` 或 `production_approved`。
- HRI/Woodbine/ERA 的 listing HTTP `200` 不能代替端到端成功；详情
  `missing_published_at` 必须 fail closed。TDN 正文成功可 technical accepted，但未验证样本
  时间不得进入 freshness candidate。

### TC-LIVE-003 第三批 12 源与 live 结构修复

- 第三批断言 `8 accepted / 4 blocked`；blocked 精确为 Canadian Thoroughbred、
  Assiniboia Downs、The National、Arab News。
- IrishRacing、SPA、Racing NSW、Tasracing 的保存 live 结构先驱动回归失败，再最小修复并
  复探 accepted。
- Racing NSW 在 listing/detail 两层排除 tips/preview；generic `Latest News` 不覆盖 RSS
  原始标题。

### TC-LIVE-004 六小时 freshness 与复用归属

- 固定 probe 时点约 `2026-07-19T17:41Z`，严格六小时窗口约
  `11:41Z..17:41Z`。verified 候选只有：
  - RTÉ `Power Blue back to winning ways at the Curragh`，`15:09:15Z`；
  - IrishRacing `Tokyo Tower shows resolution to land Curragh finale`，`16:51:00Z`。
- 地区计数为 Ireland `2`，Canada/UAE/Saudi/Australia 各 `0`。
- TDN `17:28:05Z` 因 unverified 跳过；JHR `10:09:13Z` 因超窗跳过；DRC、JCSA、SPA、
  Racing Victoria、The Straight、Racing NSW、Tasracing 的当前样本均因更早而跳过。
- 本轮样本都有精确时刻，未调用 date-only `0/1` 日兜底提升六小时计数。
- Curragh/Irish Oaks -> Ireland；Woodbine/Canadian -> Canada；无关键词保持原 US/UK
  region。Sporting Life 可 technical accepted，但 unverified time 使候选 deferred。

### TC-LIVE-005 dummy 翻译任务与持久化

- 在同一迁移临时库创建真实 RTÉ 正文 `6616` 字符文章，以
  `TRANSLATION_PROVIDER=dummy` 调用 `translate_article_task`。
- 断言返回 `translated=true`、article translation status 为 `translated`、
  `TranslationRun=success`，标题包含 `[未配置真实翻译模型]`。
- 本机 SiliconFlow/OpenAI key 均 absent；因此验收仅为任务/持久化编排，不是中文远程模型
  质量或连通性验收。

### TC-LIVE-006 离线组合

- 最新 release-candidate 组合 `214/214 OK`，follow-up `10/10`。
- 来源实现代理的独立集合为 `202` 加 `1 skip`，translation recovery `22/22`。
- `makemigrations --check` 无漂移，Django checks 通过；PostgreSQL 专项仍未执行。

## 1. 地区模型与隔离

### TC-REG-001 五个 choice 独立存在

- 断言 `RacingRegion` 包含 `ireland/canada/united_arab_emirates/saudi_arabia/australia`。
- 断言中文标签正确，值唯一，长度不超过 32。
- 断言不存在持久 `middle_east`。
- RED：当前枚举缺少五个值。

### TC-REG-002 新闻生产地区包含新五区

- 断言新闻生产/归属显式集合包含旧五区和新五区，不含 `other`。
- RED：当前 `PRODUCTION_REGIONS` 只有旧五区。

### TC-REG-003 历史赛事范围不随 choice 扩张

- 运行历史批次地区选择器，断言地区集合和变更前完全一致。
- mutation：若实现改回 `RacingRegion.values except other`，测试必须失败。
- RED：新增 choice 后若未改显式集合，该测试应捕获范围扩张。

### TC-REG-004 准实时和赛事日历不随 choice 扩张

- 断言 race-live initializer 只接受其 registry 支持地区。
- 断言赛事日历地区 tab 不自动出现尚无赛事能力的新五区。
- mutation：使用 `RacingRegion.choices` 全循环时测试失败。

### TC-REG-005 马匹补全范围保持不变

- 断言 P0 马匹补全/资料生成的显式地区集合未加入新五区。
- 断言新 choice 不产生隐式 P0 队列目标。
- 断言新闻首页接受新五区参数，但 `/horses/` 不显示新五区 tab，且新五区 query 不被马匹
  resolver 视为有效筛选。

### TC-REG-006 migration state

- 运行 `makemigrations --check --dry-run`。
- 在临时 SQLite/PostgreSQL schema 应用迁移，断言旧地区行不变、新值可写入新闻模型。
- 断言迁移不执行历史文章 data update。

## 2. 来源同步

### TC-SRC-001 五个来源身份独立

- `sync_builtin_sources()` 后存在 HRI、Woodbine、ERA、JCSA、Racing Victoria 五条来源。
- 断言 `source_site + source_mode` 唯一，地区/语言/adapter key 正确。
- RED：当前 `SourceSite` 和来源定义不存在。

### TC-SRC-002 新来源默认关闭

- 断言五个来源初始 `enabled=false`、`production_approved=false`。
- 断言 source poll 和 production window 不选择它们。
- mutation：任一默认值改为 true 时测试失败。

### TC-SRC-003 同步保护运行态

- 人工修改 enabled、production_approved、backoff、pause、interval 后再次同步。
- 断言受保护字段不被内置定义覆盖。

### TC-SRC-004 单源回滚

- 停用 Woodbine 后，加拿大来源不被选择，其余四个新地区来源状态不变。

## 3. Adapter fixture

对 HRI、Woodbine、ERA、JCSA、Racing Victoria 分别执行以下公共契约：

### TC-ADP-001 列表解析

- fixture 含两篇有效文章、导航/标签/外站链接。
- 只返回两篇站内新闻，URL canonical、source ID 稳定、无导航污染。
- RED：当前 adapter 不存在。

### TC-ADP-002 详情解析

- 正确解析标题、正文、作者、原文 URL、source language/region 和原始 HTML。
- 正文不含导航、页脚、相关报道、投注组件和版权尾注。

### TC-ADP-003 当地时间转 UTC

- HRI/多伦多/墨尔本 fixture 覆盖夏令时和非夏令时。
- Dubai/Riyadh fixture 断言固定 offset。
- ISO 自带 offset 时不得二次套用当地时区。

### TC-ADP-004 仅日期精度

- 仅有日期时写入当地 12:00，并在 evidence 标记 `precision=date` 与时区。
- 不得标记为精确到分钟。

### TC-ADP-005 缺失时间跳过

- 详情无任何可信时间时不生成可入库 draft，记录 `missing_published_at`。
- mutation：兜底 `timezone.now()` 时测试失败。
- 断言 `source_summary.published_at_missing` 计入详情阶段的缺时间错误。

### TC-ADP-006 单篇失败继续

- 第一篇空正文/selector 失败，第二篇正常。
- 断言第二篇仍入库，CrawlJob/summary 记录一条 detail failure。

### TC-ADP-007 全轮失败

- 列表有条目但所有详情失败。
- 断言任务失败，不创建 NewsArticle，错误摘要可见。

### TC-ADP-008 空列表、全详情失败和全重复分离

- 新来源 HTTP 200 但 selector 解析为 0 条：`empty_listing` 失败并进入 parse/empty backoff。
- 列表非空但详情全部失败：`all_details_failed`。
- 列表和详情成功但文章全部重复：任务成功，`new=0/duplicates>0`。
- mutation：把空列表记为普通成功无新增时测试失败。

### TC-ADP-009 HTTP/backoff 分类

- 403、429、验证码页、超时分别进入现有错误分类和保守 backoff。
- 断言不改 User-Agent/代理重试绕过。

### TC-ADP-010 有界 HTML 请求

- 覆盖非 HTTPS、off-host redirect、超过 3 次重定向、最终 host 非 allowlist、
  非 HTML 200、Content-Length/实际正文超过 2 MiB、空正文、登录页和验证码页。
- 断言 connect/read timeout 为 5/15 秒，拒绝异常响应且不交给 HTML parser。
- 断言使用固定项目 UA，不新增来源专属 UA/代理轮换。

### TC-ADP-011 单来源 canonical 去重

- 同一 source site URL 带 tracking query/fragment、多次抓取或不同 listing 发现时只生成一篇文章。
- snapshot metadata 保留 discovered source/listing。
- 不测试或实现不同 `source_site` 的通用文章合并。

### TC-ADP-012 probe 零业务写入与双轴准入

- 对 fixture/模拟 HTTP 运行 probe。
- 断言 `NewsSource/CrawlJob/NewsArticle/ProductionWindow` 计数不变。
- 输出 source key、HTTP、最终 URL、列表数、详情数、正文长度、时间 verified、
  `technical_status`、`automation_permission_status`、`effective_production_status`、
  adapter/parser version、reviewed_at 和 artifact SHA。
- 技术 accepted + 条款 unknown 必须是 `production_blocked`；只有 permission approved
  才是 `eligible`。probe 不修改 `production_approved`。

### TC-ADP-013 发布时间 evidence 持久化

- adapter 的 raw/timezone/precision/parser_version/verified 写入
  `NewsArticle.published_at_evidence` 和 `NewsSnapshot.snapshot_metadata`。
- 后续重复抓取提供未验证或较低精度时间时，不覆盖已有 verified 发布时间/evidence。

### TC-ADP-014 真实结构最小 fixture

- HRI fixture 使用 `/news/details/`、HTML entity/NBSP URL 与
  `Saturday, 20 June 2026`，断言 canonical URL 可请求且 Dublin date-only 转 UTC。
- Woodbine fixture 同时含 `/news/` 根入口、`/blog/` 与 `/woodbine-news/`，只保留后者；
  详情从 `article:published_time` 或 JSON-LD 取 Toronto 时间。
- ERA fixture 从 JSON-LD `datePublished` 取 Dubai 时间，并覆盖可见 `12 June 2026` 回退。
- JCSA fixture 模拟 `/api/news/en/0/12` HTML 片段和
  `Saturday, 22nd February 2025, 9:00pm` 详情。
- Racing Victoria fixture 模拟 sitemap XML，只保留正式文章 URL并按日期倒序；详情最小
  `__NEXT_DATA__` 同时放入 route `Title/ArticleDate`、`headless-main` 正文 RichText、
  `headless-footer` copyright RichText 和推荐组件，断言只提取主正文。
- fixture 均为最小结构，不复制完整第三方页面或正文。

### TC-ADP-015 许可与透明请求身份

- HRI、Woodbine、ERA adapter 的 permission 为 `blocked`；JCSA、Racing Victoria 为
  `unknown`；五者 effective 均保持 `production_blocked`。
- 新五源的有界请求使用可识别项目 User-Agent，不含 Chrome/Safari 浏览器品牌串。
- permission 状态不修改 `NewsSource.production_approved`。

### TC-ADP-016 精确非 200 诊断

- 模拟列表请求 `403`、`429`，断言 helper fail closed，同时 adapter/probe 保留精确
  `http_status` 和 `final_url`。
- 经 `crawl_news_source_task()` 分别模拟 `403/429`，断言
  `NewsSource.last_error_category` 为 blocked 类、达到失败阈值后使用 360 分钟 blocked
  backoff，`ProductionWindow.result_payload` 保留 `http_status/final_url/error_category`，
  `CrawlJob` 为失败且诊断可见。
- `206/300/304` 继续 fail closed；`tasks._http_status_code_from_exception()` 同时兼容新异常
  `status_code` 与既有 `response.status_code`。

### TC-ADP-017 真实列表入口边界

- JCSA `listing_url()` 返回 `/api/news/en/0/12`，内置来源展示主页仍为 `/en/news/`。
- Racing Victoria `listing_url()` 返回固定 sitemap；只有该 URL 的 listing 请求接受 XML，
  RV detail 与其他四站收到 XML 均 fail closed。
- 新五源通过受限 `user_agent` 参数发送透明 UA；共享 `DEFAULT_HEADERS`、`get_bytes()` 和旧
  `SimpleInternationalNewsAdapter` 请求行为保持不变。
- 禁止在代码、fixture、文档 artifact 中保存 Racing Victoria 前端 GraphQL 凭据。

## 4. 归属重点用例

### TC-ATT-001 英国来源的爱尔兰赛事

- Sporting Life 标题明确 Irish Derby / Curragh。
- 期望主地区 `ireland`，不得为 `united_kingdom` 或只加标签。
- RED：当前逻辑把 Ireland 关联到英国。

### TC-ATT-002 爱尔兰来源的英国赛事

- HRI 标题明确 Cheltenham，导语为爱尔兰练马师/马参赛。
- 期望主地区英国，关联爱尔兰。

### TC-ATT-003 加拿大赛事不得归美国

- TDN 标题明确 Woodbine Mile / King's Plate。
- 期望主地区加拿大。
- RED：当前只会回美国或 `other`。

### TC-ATT-004 加拿大来源的美国赛事

- Woodbine 标题明确 Breeders' Cup，导语含加拿大马。
- 期望主地区美国，关联加拿大。

### TC-ATT-005 阿联酋与沙特分别归属

- Meydan / Dubai World Cup -> 阿联酋。
- Saudi Cup / King Abdulaziz Racecourse -> 沙特。
- 同时出现两个强赛事中心且无法判定叙事中心 -> `needs_review`。
- 断言不存在 `middle_east` 持久值。

### TC-ATT-006 澳大利亚正式归属

- Flemington / Melbourne Cup / Randwick / The Everest -> 澳大利亚。
- 不得产生 `out_of_scope_title_region` 或 `other`。

### TC-ATT-007 澳大利亚来源的英国赛事

- Racing Victoria 报道澳大利亚马参加 Royal Ascot，标题有强英国赛事信号。
- 期望英国主地区、澳大利亚关联地区。

### TC-ATT-008 关联地区上限

- 构造超过 3 个可信地区。
- 期望 `needs_review`，不静默截断为错误主地区。

### TC-ATT-009 旧五区回归

- 运行现有多地区归属目标测试/Gold fixture。
- 断言日本、香港、英国、法国、美国的既有高置信行为无回归。
- 新规则版本不得自动继承旧版本生产资格。

### TC-ATT-010 历史文章不自动改写

- 迁移和来源同步后，旧 `other`、英国+`ireland` 标签文章保持原值。
- 只读候选导出包含命中新五区的记录，未执行 commit。

### TC-ATT-011 实际 mode off 端到端候选

- settings：全局 attribution mode `off`，source-scoped candidate 开启，只 allowlist HRI。
- 从 HRI adapter draft 经 `upsert_article_from_draft()` 入库 Cheltenham 跨境稿。
- 断言主地区仍为来源地区 `ireland`，不创建 related row；候选为英国主/爱尔兰关联，保存
  `review_candidate`、规则版本、置信度和冲突原因。
- 断言文章带 `region_review_required`/人工审核硬门，不能发布或推 QQ。
- 通过编辑服务明确应用英国主/爱尔兰关联并锁定后，地区状态才可视为已确认。
- allowlist 外旧来源在 mode off 下保持现有行为。

## 5. UI、窗口和 QQ

### TC-UI-001 公共筛选可到达

- 首页可选择爱尔兰、加拿大、澳大利亚、阿联酋、沙特。
- UAE/沙特在“中东”视觉分组下，但 query 值不同。
- 无 JavaScript 时仍有可访问链接/表单。
- 马匹索引与赛事日历不展示、不接受本次新五区。

### TC-UI-002 移动布局

- 390px 宽度无页面级横向溢出，新地区选择可触控、可键盘访问。
- 空地区显示清晰空状态，不影响综合流。

### TC-WIN-001 新地区默认无窗口

- 默认 allowed regions 不含新五区时，不创建 crawl/publish/QQ 窗口。
- 启用单个地区 crawl 时只影响该地区。

### TC-WIN-002 自动发布默认人工审核

- 新地区文章未显式进入 auto-publish region/source allowlist 时必须人工审核。

### TC-QQ-001 QQ 独立订阅

- 使用 `push_scope=all_public` 隔离验证地区订阅，不把 OFFICIAL 来源误当 ranked 高价值来源。
- 群只允许 `canada` 时可匹配已公开且地区已锁定的加拿大主/关联文章，不匹配美国普通文章。
- 群只允许 `united_arab_emirates` 时不自动匹配已锁定的 `saudi_arabia`。
- 同一跨地区文章对同一群仍只发送一次。

### TC-QQ-002 旧群兼容

- `allowed_regions=[]` 或非法值继续只允许日本，不自动获得新五区。

### TC-OBS-001 地区审计

- 新五区各有来源、新增、重复、缺时间、详情失败、翻译、门禁、公开和 QQ 字段。
- 查询数量保持有界，不随来源数线性 N+1。

## 6. 验证分层

### RED

- 先提交/运行上述最小目标测试；失败必须是缺枚举、缺 adapter、缺归属规则或缺 UI 行为。
- 不接受因 fixture 错误、import error、迁移冲突或环境缺依赖造成的伪 RED。
- RED 命令、失败测试名和核心 assertion 写回本文件的实施证据区。

### GREEN

- 聚焦模型/来源/adapter/归属/UI/窗口/QQ 测试。
- 受影响的现有多地区、来源轮询、新闻内容边界和历史/准实时地区隔离回归。
- `DB_ENGINE=sqlite python manage.py check`
- `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test <target modules> --noinput`
- 临时 PostgreSQL migration/constraint smoke。

### 真实只读 probe

- 每个候选来源独立请求预算，默认列表 1 次、详情最多 2 次。
- 输出 technical/permission/effective 三轴状态、条款、HTTP、解析、日期、版本和 artifact SHA。
- 不写业务表、不翻译、不发布、不推 QQ。

### 发布前

- `python manage.py makemigrations --check --dry-run`
- 受影响完整回归
- `docker compose -f docker-compose.prod.yml config`
- `docker compose -f docker-compose.prod.lowcost.yml config`
- `git diff --check`
- 独立代码 reviewer 原生 read-only review

## 7. 实施证据

待实现阶段填写：

- RED：
  - 日期：`2026-07-19`
  - 命令（worktree 的 `server/` 目录；通过 `PATH` 使用仓库既有 `.venv`，命令主体保持
    `python manage.py test`）：

    ```bash
    PATH="/Users/mentianlu/Code/umanews/.venv/bin:$PATH" \
      DB_ENGINE=sqlite \
      CELERY_TASK_ALWAYS_EAGER=true \
      python manage.py test stable.test_new_region_news_sources --noinput
    ```

  - 结果：exit `1`；收集 `22` 个逻辑测试，`21` 个逻辑测试失败、`1` 个通过。五来源
    adapter 合同及澳洲双样本使用 `subTest`，因此 unittest 汇总为
    `FAILED (failures=38)`。临时 SQLite 测试库正常创建/销毁，
    `System check identified no issues (0 silenced)`，无 `ERROR`、import error、fixture
    error 或真实网络请求。
  - 失败测试名：
    - `ModeOffCandidateGateTests.test_source_scoped_candidate_keeps_source_region_and_blocks_publish_and_qq`
    - `NewRegionAdapterContractTests.test_each_adapter_marks_date_only_as_local_noon`
      （HRI/Woodbine/ERA/JCSA/Racing Victoria 五个 subTest）
    - `NewRegionAdapterContractTests.test_each_adapter_parses_detail_body_author_and_verified_local_time`
      （五个 subTest）
    - `NewRegionAdapterContractTests.test_each_adapter_parses_only_canonical_internal_listing_items`
      （五个 subTest）
    - `NewRegionAdapterContractTests.test_each_adapter_rejects_detail_without_trusted_published_time`
      （五个 subTest）
    - `NewRegionAttributionTests.test_australian_events_are_not_out_of_scope`
      （Melbourne Cup/Flemington 与 The Everest/Randwick 两个 subTest）
    - `NewRegionAttributionTests.test_australian_source_reporting_royal_ascot_has_australia_related`
    - `NewRegionAttributionTests.test_canadian_source_reporting_breeders_cup_is_us_with_canada_related`
    - `NewRegionAttributionTests.test_global_source_reporting_woodbine_is_canada`
    - `NewRegionAttributionTests.test_irish_source_reporting_cheltenham_is_uk_with_ireland_related`
    - `NewRegionAttributionTests.test_uae_and_saudi_are_independent_and_conflicts_require_review`
    - `NewRegionAttributionTests.test_uk_source_reporting_irish_derby_is_ireland`
    - `NewRegionCrawlOutcomeTests.test_http_200_empty_listing_is_failed_as_empty_listing`
    - `NewRegionCrawlOutcomeTests.test_nonempty_listing_with_no_parsable_details_is_all_details_failed`
    - `NewRegionIdentityTests.test_five_regions_have_independent_persistent_choices`
    - `NewRegionIdentityTests.test_five_source_sites_and_adapter_keys_are_registered`
    - `NewRegionIdentityTests.test_news_regions_expand_without_expanding_horse_or_race_data`
    - `NewRegionProbeContractTests.test_only_approved_permission_is_effectively_eligible`
    - `NewRegionProbeContractTests.test_technical_acceptance_with_unknown_permission_is_blocked`
    - `NewRegionSourceDefinitionTests.test_builtin_definitions_have_correct_identity_and_default_off`
    - `NewRegionSourceDefinitionTests.test_source_sync_creates_five_independent_sources_default_off`
  - 核心断言摘要：
    - `RacingRegion`/`SourceSite`、`PRODUCTION_REGIONS`、来源定义和 adapter registry
      均缺新五区/五来源；新闻/马匹 tab 尚未拆分。
    - 五 adapter 合同在 registry 缺失处 RED；后续实现后会继续校验列表 canonical URL、
      正文边界、Dublin/Toronto/Dubai/Riyadh/Melbourne 当地时间、date-only 当地中午、
      evidence 和 `missing_published_at`。
    - Sporting Life 的 Irish Derby 仍归英国；HRI 跨境稿缺爱尔兰关联；Woodbine/加拿大
      仍回美国/`other`；UAE/沙特仍为 `other`；澳洲仍回美国或 `other`。
    - HTTP 200 空列表当前被当作成功；全详情失败仍只有通用 `parse failed`，未给出
      `empty_listing`/`all_details_failed` 稳定分类。全重复用例已通过，证明该分支现有行为为
      “成功、`new=0/duplicates=1`”。
    - probe 缺
      `technical_status/automation_permission_status/effective_production_status`、版本、审核时间和
      artifact SHA；probe 零业务写入断言已执行且没有伪失败。
    - 全局 mode `off` + HRI source allowlist 时未生成 `review_candidate`，因此尚无
      `region_review_required` 发布/QQ 硬门可验收。
- GREEN：
  - 日期：`2026-07-19`
  - 专用测试命令：

    ```bash
    PATH="/Users/mentianlu/Code/umanews/.venv/bin:$PATH" \
      DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true \
      python manage.py test stable.test_new_region_news_sources --noinput
    ```

  - 结果：exit `0`；`30/30` 通过，`System check identified no issues`。在原 22 个
    逻辑用例基础上补充有界 HTTP（HTTPS/host/redirect/HTML/2 MiB/5s+15s/登录验证码）、
    发布时间 evidence 防降级、新闻/马匹/赛事 resolver 隔离以及 QQ
    `all_public/high_value_only/allowed_regions/attribution_locked` 独立门禁。
  - 聚焦归属与法国时间回归：

    ```bash
    PATH="/Users/mentianlu/Code/umanews/.venv/bin:$PATH" \
      DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true \
      python manage.py test \
        stable.test_new_region_news_sources \
        stable.test_multiregion_attribution_change \
        stable.test_france_news_freshness_change --noinput
    ```

  - 结果：exit `0`；`130` 个测试通过、`1` 个既有 live-network probe 用例跳过。原
    “Dubai Racing Club 属于 out-of-scope/other”的旧 fixture 已改为真正未建模的
    `World's Best Racehorse Rankings` fixture；UAE 现在由新强信号测试负责，未弱化
    `other` 关联地区持久化断言。
  - 既有来源/QQ/抓取/公共首页回归：

    ```bash
    PATH="/Users/mentianlu/Code/umanews/.venv/bin:$PATH" \
      DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true \
      python manage.py test \
        stable.tests.InternationalSourceMetadataTests \
        stable.tests.QQAutoPushTests \
        stable.tests.CrawlAutoTranslateTests \
        stable.tests.PublicHomeInfoFeedTests --noinput
    ```

  - 结果：exit `0`；`69/69` 通过。
- PostgreSQL：
  - 未执行临时 PostgreSQL smoke；本轮无独立临时 PostgreSQL 实例。SQLite 测试数据库已从
    migration `0001` 应用至新增 `0047` 并正常销毁。此项仍是 review/发布前未完成验证。
- 真实 probe：
  - 已执行五站点显式低预算 probe；五源 HTTP 200 但技术状态均为 `deferred`。
  - HRI/Woodbine/ERA permission 为 `blocked`，JCSA/Racing Victoria 为 `unknown`；
    当前没有来源 `effective_production_status=eligible`。
  - 首轮 artifact、真实结构与补救测试范围见 `design.md` 第 4.4、4.5、11 节；修复后必须
    在同一预算内重跑，不能用 fixture GREEN 替代真实 accepted。
- 回归：
  - `DB_ENGINE=sqlite python manage.py check`：exit `0`。
  - `DB_ENGINE=sqlite python manage.py makemigrations --check --dry-run`：`No changes detected`。
  - `git diff --check`：exit `0`。
- review：
  - 首次原生 read-only review 为 `REVISE`；六项修复后，最终限定复审为
    `VERDICT: APPROVED`，完整证据见第 9 节。

## 8. 首次代码 review 修复证据

首次原生只读 review 会话：
`019f76e0-c8a5-7330-9da1-f51f279a0dd0`，结论 `VERDICT: REVISE`。本轮仅处理其六项
actionable findings；这是首次 review 的历史结论，最终限定复审见第 9 节。

### 修复前 RED

命令：

```bash
PATH="/Users/mentianlu/Code/umanews/.venv/bin:$PATH" \
  DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true \
  python manage.py test stable.test_new_region_news_sources --noinput
```

结果：exit `1`；收集 `36` 个测试，unittest 汇总 `FAILED (failures=11)`。失败均为目标漏洞，
没有 import、fixture、数据库或真实网络错误：

- 人工编辑器 publish 对“未锁定 `review_candidate`”及残留
  `region_review_required` blocker 两个 subTest 均返回 `302` 并绕过门禁。
- 日文 UAE/Saudi 两个 subTest 均错误保留 `japan`。
- probe `--limit=3` 未抛 `CommandError`。
- 默认 FIRST_VERSION keys/probes 仍包含五个新来源。
- bounded HTTP 对 `206/300/304` 三个 subTest 均未拒绝。
- 人类可读 probe 的 accepted/error 两个分支均缺 technical/permission/effective、版本、
  reviewed_at 和 artifact SHA。

P1 直接路径补强另取得一次聚焦 RED：

```bash
PATH="/Users/mentianlu/Code/umanews/.venv/bin:$PATH" \
  DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true \
  python manage.py test \
    stable.test_new_region_news_sources.NewRegionManualPublishGateTests --noinput
```

结果：exit `1`，`FAILED (failures=1)`；同一次 publish POST 勾选
`attribution_locked=on` 仍可把数据库中尚未锁定的候选直接发布。修复后该聚焦用例与专用
`36/36` 均 GREEN：发布门同时检查请求前持久状态和表单内当前状态，必须先独立保存地区确认，
再另行发起 publish。

### 修复后 GREEN

同一专用命令结果：exit `0`，`36/36` 通过。

六项关闭证据：

1. 人工 publish、自动 publish、QQ 统一复用
   `region_review_publish_blocker()`；候选未锁定或 blocker 尚存时视图返回明确错误且不改
   `workflow_status/published_to_web_at`。
2. UAE/Saudi 正式地区/事件词表加入日文强信号：
   `アラブ首長国連邦/ドバイワールドカップ/メイダン` 与
   `サウジアラビア/サウジカップ/リヤド/キングアブドゥルアジーズ競馬場`。
3. probe `--limit` 只允许 `1-2`，超出 fail closed。
4. 新五来源保留在显式 adapter registry，但移出无参和仅 `--mode` 使用的
   FIRST_VERSION 默认外联矩阵。
5. bounded HTTP 在重定向处理后只接受精确 HTTP `200`。
6. 人类可读 probe 在成功和错误分支都先输出完整三轴 contract、版本、审核时间及 SHA。

### 直接回归

```bash
PATH="/Users/mentianlu/Code/umanews/.venv/bin:$PATH" \
  DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true \
  python manage.py test \
    stable.test_new_region_news_sources \
    stable.test_multiregion_attribution_change \
    stable.test_france_news_freshness_change --noinput
```

结果：exit `0`；`136` 个通过，`1` 个既有 live-network probe 跳过。

```bash
PATH="/Users/mentianlu/Code/umanews/.venv/bin:$PATH" \
  DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true \
  python manage.py test \
    stable.tests.InternationalSourceMetadataTests \
    stable.tests.QQAutoPushTests \
    stable.tests.CrawlAutoTranslateTests \
    stable.tests.PublicHomeInfoFeedTests --noinput
```

结果：exit `0`；`69/69` 通过。

- `DB_ENGINE=sqlite python manage.py check`：exit `0`。
- `DB_ENGINE=sqlite python manage.py makemigrations --check --dry-run`：
  `No changes detected`。
- `git diff --check`：exit `0`。
- 同一 reviewer 的限定复审：`VERDICT: APPROVED`，完整身份与前后一致性见第 9 节。

## 9. 最终限定复审证据

- 首次 review 的 `F1-F6` 均为 `CLOSED`。最终限定复审 native session：
  `019f76f0-ef8b-71d1-a0ad-246d26352f0e`。
- Header：
  - workdir：`/Users/mentianlu/Code/umanews/.worktrees/add-new-region-news-sources`
  - model：`gpt-5.6-sol`
  - approval：`never`
  - sandbox：`read-only`
- 复审命令 exit `0`，结论 `VERDICT: APPROVED`。
- 复审前后 helper 均 exit `0`，原始输出逐字一致：
  - `FINGERPRINT_SHA256=7858ebb1e71c4f19860493c58dca9362c39c10fd99d770ebe3c310d0f23bcf3e`
  - `content_manifest_sha256=24608da5ef542932c3e4a6535e549cc5ce0b253862f1a5b9e55378e2a4e97064`
  - `tracked_diff_sha256=11e460c7ebccba7ade08daabe4ac9231de27d93f36fcd19a27c07a01de057c57`
  - `untracked_manifest_sha256=b2d6b831aa80d241a3bae90fa1a07dc84c4e815bb93fcaae2e1cc0e5cec3a66d`
- Reviewer 的三项非阻断、范围外后续建议保持未完成：旧 adapter `empty_listing` 影响、
  非 ISO visible date 解析、地区关键词 substring boundary。它们不改变本轮
  `APPROVED`，也不表示已经验证。
- 上述 hash 覆盖本次状态文档回写前的候选。本次 docs patch 已使 fingerprint 变化，
  `current_state`、项目文档和本 change artifact 的回写本身未被该代码复审覆盖；第一次
  docs-only 一致性复审结果见第 10 节。

## 10. Docs-only 一致性复审与 residual gap

- 第一次 docs-only native review session：
  `019f76fb-5494-7a63-b9e5-b4d5a6985bff`；sandbox `read-only`，命令 exit `0`，
  fingerprint 前后一致。
- 结论：`VERDICT: REVISE`。Findings 指出共享 `RacingRegion` choices 对若干结构化字段的
  choices/后台输入影响、临时 PostgreSQL 未执行、非 200 精确分类能力和本文阶段描述不准确；
  受审 current docs 基线未获批准。
- 本 change 新有界 HTTP 路径的已有测试只证明重定向处理后仅精确 `200` 可接受，
  `206/300/304` fail closed。当前非 200 响应由新 helper 抛 `ValueError`，新 adapter
  未记录 `last_listing_http_status`，所以没有测试或实现能保证对应 probe/crawl 保留精确
  `403/429` 分类；该项保持 residual gap。
- 本轮仅修正上述文档，不改代码、测试、配置或迁移。修复后由同一 reviewer 在 native
  session `019f7705-375e-7ee3-aaa4-8125215be390` 复审为 `VERDICT: APPROVED`。
  后续真实 probe 与补救文档再次改变 fingerprint，旧批准不覆盖当前候选。

## 11. 首轮真实 probe 与补救 RED

- 首轮真实 probe 已完成，结果与 artifact SHA 记录在 `design.md` 第 11 节。
- 补救 RED 必须仅修改本测试文件和本专项测试文档，不得先改运行代码；至少覆盖
  TC-ADP-014 至 TC-ADP-017。
- RED 命令沿用本文件既有专用测试命令。失败必须来自当前五 adapter 的真实入口、日期、
  permission、透明 User-Agent 或精确状态诊断不符合，不得来自网络、坏 fixture、import
  或数据库环境。执行证据见第 12 节。

## 12. 真实结构与 HTTP 诊断补救 RED

执行日期：`2026-07-19`。本轮只修改：

- `server/stable/test_new_region_news_sources.py`
- `docs/changes/add-new-region-news-sources/test_cases.md`

未修改 adapter、HTTP helper、task、model、migration 或生产配置，也未进行真实网络请求。

执行命令：

```bash
cd /Users/mentianlu/Code/umanews/.worktrees/add-new-region-news-sources/server
PATH="/Users/mentianlu/Code/umanews/.venv/bin:$PATH" \
  DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true \
  python manage.py test stable.test_new_region_news_sources --noinput
```

结果：exit `1`；收集 `51` 个测试，unittest 汇总
`FAILED (failures=37)`。临时 SQLite 数据库正常创建与销毁，
`System check identified no issues (0 silenced)`；无 `ERROR`、import error、fixture error
或真实网络请求。原有 `36` 个测试仍全部通过。

新增 `15` 个测试中，以下 `3` 个已 GREEN：

1. `NewRegionRequestIsolationTests.
   test_bounded_helper_default_and_legacy_get_bytes_contract_are_unchanged`
   - 证明未传新参数时 bounded helper 仍使用旧 `DEFAULT_HEADERS`；
   - 证明 `get_bytes()` 与 Sporting Life 既有 adapter 调用参数未改变。
2. `NewRegionFixtureSecretSafetyTests.
   test_new_region_code_docs_and_fixtures_contain_no_graphql_credentials`
   - 扫描本 change adapter/HTTP/task/test/docs 范围；
   - 当前没有 GraphQL credential 赋值或常见 secret prefix。
3. `NewRegionStructuredHttpFailureTests.
   test_task_status_extractor_keeps_legacy_response_compatibility`
   - 证明既有 `exc.response.status_code` 路径仍能提取 HTTP 状态。

其余 `12` 个新测试为目标 RED；subTest 展开后共 `37` 条失败断言：

- permission `3`：HRI、Woodbine、ERA 当前仍为 `unknown`，未锁为 `blocked`；
  JCSA/Racing Victoria 的 `unknown` 与所有五来源 effective fail-closed 断言已经通过。
- 真实结构 `6`：HRI 未限定 `/news/details/` 且未进入 Unicode canonical/date 断言；
  Woodbine 仍选择 `/news/` 而非 `/woodbine-news/`；ERA JSON-LD/可见长日期均缺时间；
  JCSA 仍使用旧 `/en/news/media-services/`；Racing Victoria 仍使用 `/news` 而非
  sitemap。
- 请求隔离 `11`：五来源 listing 都未传透明可识别 UA，五来源 detail 未显式限制 HTML
  content types，RV sitemap 也不能显式接受 XML；默认 XML 拒绝已经通过。
- 结构化 HTTP `17`：helper 的 403/429 异常没有 `status_code/final_url`；adapter 和 probe
  均丢失相同字段；task 只兼容 `exc.response.status_code`，不兼容 `exc.status_code`；
  crawl 因此分类为 `unknown`、只回退 `60` 分钟，并且窗口 payload 缺
  `http_status/final_url`。与此同时，失败 `ProductionWindow`、失败 `CrawlJob` 及安全错误
  摘要均已被创建并可见，证明 RED 不来自任务或数据库 fixture 缺陷；legacy
  `exc.response.status_code` 路径保持兼容。

具体最小 fixture 已覆盖：

- HRI `/news/details/`、`Saturday, 20 June 2026`、HTML NBSP 与 Unicode curly quote；
- Woodbine `/woodbine-news/` allowlist、`/news/`/`/blog/` 排除、
  `article:published_time`、JSON-LD `datePublished` 与 `.entry-content`；
- ERA JSON-LD `datePublished` 与可见 `12 June 2026`；
- JCSA `/api/news/en/0/12` HTML fragment、`h1`、
  `Saturday, 22nd February 2025, 9:00pm` 与 `.content-area`；
- Racing Victoria sitemap XML only listing，以及限定
  `props.pageProps.layoutData.sitecore.route`、`ArticleDate` 和
  `headless-main/ RichText` 的 `script#__NEXT_DATA__` 详情；footer、
  `DCAArticleList`/recommended 均必须排除。

本轮 `git diff --check` 对上述两个文件 exit `0`。

## 13. 严格实现后的旧 fixture 纠偏与 GREEN

严格实现落地后，首次运行完整专用测试收集 `51` 项，结果为：

```text
FAILED (failures=4, errors=5)
Ran 51 tests
```

新增真实结构、permission、透明 UA/XML、结构化 HTTP/crawl 与 secret scan 的 `15/15`
已经通过；剩余九处均为旧通用合成 fixture 与已批准严格入口冲突，不是运行时回归：

- HRI 仍使用错误的 `/news-and-media/sample-one`；
- Woodbine 仍使用错误的 `/news/sample-one`；
- Racing Victoria 仍使用无日期 `/news/sample-one`，且详情缺
  `script#__NEXT_DATA__`；
- JCSA 通用正文只有 `article.content`，缺真实 `.content-area`；
- HRI、Woodbine、Racing Victoria 的缺时用例从上述无效 listing 取首项，产生
  `IndexError`。

只修改测试 fixture 后：

- HRI 通用 fixture 改为 `/news/details/`；
- Woodbine 改为 `/woodbine-news/`；
- JCSA listing 改为 `/api/news/en/0/12`，正文加入 `.content-area`；
- Racing Victoria listing 改为含日期正式文章 URL 的 sitemap XML；详情与缺时场景均使用
  `script#__NEXT_DATA__`、`ArticleDate`、`headless-main/ RichText`；
- 保留原通用不变量：两条站内 canonical URL、稳定 source ID、tracking/fragment 去除、
  `source_site/source_mode`、当地时间转 UTC、date-only 当地中午、verified evidence 与
  `missing_published_at` fail-closed。

完整专用命令：

```bash
cd /Users/mentianlu/Code/umanews/.worktrees/add-new-region-news-sources/server
PATH="/Users/mentianlu/Code/umanews/.venv/bin:$PATH" \
  DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true \
  python manage.py test stable.test_new_region_news_sources --noinput
```

结果：exit `0`，`51/51` 通过，`System check identified no issues (0 silenced)`。

新增严格测试聚焦命令：

```bash
PATH="/Users/mentianlu/Code/umanews/.venv/bin:$PATH" \
  DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true \
  python manage.py test \
    stable.test_new_region_news_sources.NewRegionRealStructureFixtureTests \
    stable.test_new_region_news_sources.NewRegionPermissionMatrixTests \
    stable.test_new_region_news_sources.NewRegionRequestIsolationTests \
    stable.test_new_region_news_sources.NewRegionStructuredHttpFailureTests \
    stable.test_new_region_news_sources.NewRegionFixtureSecretSafetyTests \
    --noinput
```

结果：exit `0`，`15/15` 通过。没有修改 adapter、HTTP helper、task、model、migration 或
生产配置，也没有真实网络请求。

## 14. 第二轮真实证据对齐 RED

保存的现场证据进一步确认：

- JCSA 详情日期节点不是通用 `.date`，而是
  `.text-black-body.font-inter.text-small-body`，样本原文为
  `Sunday, 22nd March 2026, 5:00pm`；
- Racing Victoria 正式详情 URL 使用 `/news/YYYY/MM/DD/slug`，不是此前 fixture 的
  `/news/YYYY-MM-DD/slug`。

本轮只修改测试与本文档，未修改运行时代码，也未联网。fixture 调整如下：

- JCSA 当前详情路径改为 `/en/news/20260323_arc_videos`；
- 详情 fixture 使用精确 `text-small-body` class，断言 Riyadh 当地
  `2026-03-22 17:00` 转为 `2026-03-22T14:00:00Z`，evidence 保留完整 raw，
  `precision=minute`；
- JCSA 通用时间/仅日期合同也改用相同真实 class，不再依赖 `.date`；
- `ADAPTER_CASES`、RV 通用 sitemap、严格 sitemap、预期路径及详情 URL 全部改为
  `/news/YYYY/MM/DD/slug`；
- notices、videos、undated URL 仍必须被排除，正式文章仍按日期倒序；
- 缺时合同直接构造合法 `SourceArticleStub`，不再从尚未被 parser 接受的 listing 取
  `stubs[0]`，因此 RED 不会退化为 `IndexError`。

执行命令：

```bash
cd /Users/mentianlu/Code/umanews/.worktrees/add-new-region-news-sources/server
PATH="/Users/mentianlu/Code/umanews/.venv/bin:$PATH" \
  DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true \
  python manage.py test stable.test_new_region_news_sources --noinput
```

结果：exit `1`；收集 `51` 项，`FAILED (failures=5)`，即 `46` 项通过；临时 SQLite
数据库正常创建与销毁，`System check identified no issues (0 silenced)`，无 `ERROR`、
import/fixture/database 错误或真实网络请求。

五条失败精确分为：

1. JCSA 通用 minute 时间合同：当前 adapter 未选择 `text-small-body`，抛
   `missing_published_at`，测试转为明确 assertion failure。
2. JCSA 通用 date-only 合同：同上。
3. JCSA 当前真实详情合同：同上；尚未进入 UTC/evidence 后续断言。
4. RV 通用 canonical listing：当前 regex 只接受 `YYYY-MM-DD`，斜杠日期 sitemap 返回
   `0` 条，预期 `2` 条。
5. RV 严格 sitemap/`__NEXT_DATA__` 合同：同上，预期两条按日期倒序的正式文章，实际为空。

权限、UA/XML、结构化 HTTP、crawl/backoff、legacy compatibility、secret scan 以及其他
既有断言均继续通过。

## 15. 内置来源 URL 与许可 notes 最小 RED

第二轮 JCSA/Racing Victoria 运行时修复完成后，完整专用测试先恢复为 `51/51` GREEN。
随后只在 `NewRegionSourceDefinitionTests` 的既有来源定义用例中加入精确端点与
machine-readable permission note 合同，测试总数仍为 `51`：

| adapter key | 展示 homepage | 技术 feed | notes token |
| --- | --- | --- | --- |
| `hri_news` | `https://www.hri.ie/news-and-media` | 同左 | `automation_permission_status=blocked` |
| `woodbine_news` | `https://woodbine.com/news/` | 同左 | `automation_permission_status=blocked` |
| `emirates_racing_authority` | `https://emiratesracing.com/news/` | 同左 | `automation_permission_status=blocked` |
| `jcsa_news` | `https://jcsa.sa/en/news/` | `https://jcsa.sa/api/news/en/0/12` | `automation_permission_status=unknown` |
| `racing_victoria_news` | `https://www.racingvictoria.com.au/news` | `https://www.racingvictoria.com.au/sitemap.xml` | `automation_permission_status=unknown` |

原有 identity、region、language、`enabled=false` 与 `production_approved=false` 断言保持
不变；来源同步测试也未删除或弱化。

执行命令：

```bash
cd /Users/mentianlu/Code/umanews/.worktrees/add-new-region-news-sources/server
PATH="/Users/mentianlu/Code/umanews/.venv/bin:$PATH" \
  DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true \
  python manage.py test stable.test_new_region_news_sources --noinput
```

结果：exit `1`；`Ran 51 tests`，`FAILED (failures=12)`，即 `39` 项通过；临时 SQLite
数据库正常创建与销毁，`System check identified no issues (0 silenced)`，无 `ERROR`、
import/fixture/database 错误或真实网络请求。

十二条失败全部来自尚未更新的来源定义：

- HRI、Woodbine、ERA：各缺新闻入口 homepage 与 blocked note，共 `6` 条；
- JCSA：展示 homepage、API feed、unknown note，共 `3` 条；
- Racing Victoria：展示 homepage、sitemap feed、unknown note，共 `3` 条。

HRI、Woodbine、ERA 的既有 feed 已符合合同；其他适配器、permission/UA/XML、HTTP/crawl、
attribution、发布门禁与 secret scan 测试继续通过。

## 16. 最终补救 GREEN 与受控 proof

三轮补救 RED 均已闭环：

1. 真实结构、permission、透明 UA/XML 和结构化 HTTP/crawl 诊断：完整范围先得到
   `37` 条 failure、`0 ERROR`；
2. JCSA 当前真实日期 class 与 Racing Victoria 斜杠日期路径：`5` 条 failure、`0 ERROR`；
3. 五条内置来源 homepage/feed 与 permission notes：`12` 条 failure、`0 ERROR`。

最终独立运行：

```bash
PATH="/Users/mentianlu/Code/umanews/.venv/bin:$PATH" \
  DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true \
  python manage.py test \
    stable.test_new_region_news_sources \
    stable.test_multiregion_attribution_change \
    stable.test_france_news_freshness_change --noinput
```

结果：exit `0`；`151` 个通过，`1` 个既有 live-network probe 跳过。

```bash
PATH="/Users/mentianlu/Code/umanews/.venv/bin:$PATH" \
  DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true \
  python manage.py test \
    stable.tests.InternationalSourceMetadataTests \
    stable.tests.QQAutoPushTests \
    stable.tests.CrawlAutoTranslateTests \
    stable.tests.PublicHomeInfoFeedTests --noinput
```

结果：exit `0`；`69/69` 通过。`manage.py check` 无问题，
`makemigrations --check --dry-run` 为 `No changes detected`，`git diff --check` 通过。

已保存的当前 JCSA 页面离线解析结果：

- title：`ARC2026 Speakers’ Presentations and Videos Now Available on ARF Website`
- published_at：`2026-03-22T14:00:00+00:00`
- body length：`724`
- evidence：raw `Sunday, 22nd March 2026, 5:00pm`、timezone `Asia/Riyadh`、
  precision `minute`

补救在线 proof 没有被重跑成 accepted：

- JCSA artifact `0244333e5c84ea9da8d55e604cae6ea9a1c3c1fde79186da3615e0177ed753ca`
  为 HTTP `200`、list `12`、technical `deferred`；
- Racing Victoria artifact
  `d35b541c698a94aba8e5b4979d8f0d3a64eba81c306b50c28bce5ce1fa304c9f`
  为 HTTP `200`、list `0`、technical `deferred`。

两者请求预算已经用完，修复后只使用保存证据与 fixture 验证；HRI/Woodbine/ERA 因
permission `blocked` 没有补救联网。当前没有来源满足
`technical accepted + permission approved`。

## 17. 最新主线集成与完整基线对照

候选已在新 worktree
`/Users/mentianlu/Code/umanews/.worktrees/add-new-region-news-sources-integrated`、分支
`codex/add-new-region-news-sources-integrated` 叠加
`origin/main@566a9b1012aac7fe52ad7aec793ab0ff4b9eae18`。主线新增
`0046_race_live_manual_verification_contract` 后，本 change migration 顺延为
`0047_alter_externaldataimporterror_racing_region_and_more` 并依赖主线 `0046`；
`makemigrations --check --dry-run` 无漂移。

主线集成暴露并关闭两项本 change 直接问题：

- `historical_batch_pipeline` 在 `_VALID_REGIONS` 改用显式 `RACE_DATA_REGIONS` 时漏保留
  `RacingRegion` import，完整回归触发 module import `NameError`；恢复 import 后消失，
  没有退回全 choices。
- 旧 `test_ireland_content_is_temporarily_grouped_with_uk_and_tagged` 改为独立 Ireland
  合同：Irish Derby/Curragh 的 primary 和唯一地区均为 Ireland，不追加 legacy tag；该
  测试在 integrated 候选直接 GREEN，无运行时特例。

最新直接验证：

- 新地区专用：`54/54`；
- 新地区/归属/法国时间：`154` 个通过，`1` 个既有 live-network skip；
- 既有来源/QQ/抓取/首页与爱尔兰旧合同纠偏：`70/70`；
- event 924 initialization/manual/transition/realtime 邻接：`200` 个通过，
  `2` 个 PostgreSQL-only skip；
- Django check、migration drift、`git diff --check`：通过。

从仓库根使用 `TMPDIR=/private/tmp` 运行完整 `stable`：

```text
Ran 2078 tests
FAILED (failures=2, errors=12, skipped=33)
```

本 change 的 Ireland 旧合同 failure 与 `RacingRegion` import error 均已消失。剩余精确
`14` 项在干净最新 `origin/main` detached worktree 中以同一测试集合复现为
`2 failure / 12 error`：

- current-year CSV 测试未提供新增 descriptor/approval/cutoff；
- `tmp/run_current_year_source_override.py`、`tmp/run_known_calendar_shards.py` 未跟踪；
- historical runner 的 `parse_gap_json` 与子进程 import 路径既有合同。

因此完整全绿仍受主线基线阻断，但本 change 的所有直接和重叠路径均已 GREEN；本专项不扩展
授权去修复上述历史 runner/current-year 测试。

## 18. 最新代码审查 P2 的 RED/GREEN

原生只读代码审查会话 `019f78e0-c31f-7c41-8885-7010617e379d` 首轮结论为
`VERDICT: REVISE`，指出：

1. `RaceEventForm` 与 `HorseProfileForm` 重建 choices 时排除了既有合法值 `other`，
   导致旧记录修改 notes/review_notes 也无法保存；
2. Ireland 来源上下文以裸子串匹配 `hri`，会把
   `Thrilling finish at Ascot` 错误识别为 Ireland 关联证据。

先只新增三项无网络回归测试，旧实现精确结果为：

```text
Ran 3 tests
FAILED (failures=3)
```

两项表单测试均得到 `other 不在可用的选项中`，Ascot 测试的主地区虽为英国，但 related
错误包含 Ireland。最小修复后：

- 新增仅供 ModelForm 使用的旧五区加 `other` choices；`RACE_DATA_REGIONS`、
  `HORSE_PROFILE_REGIONS`、`RACE_LIVE_SUPPORTED_REGIONS` 均未扩大；
- Ireland 来源上下文的 ASCII 关键词复用
  `source_term_matches_text(..., SourceLanguage.ENGLISH)`。

最新验证：

```text
目标审查回归：3/3
stable.test_new_region_news_sources：54/54
新地区 + 多地区归属 + 法国时间：154 passed / 1 existing skip
相邻来源、QQ、抓取、首页与旧爱尔兰合同：70/70
event 924 重叠：200 passed / 2 PostgreSQL-only skip
Django check：0 issues
makemigrations --check --dry-run：No changes detected
git diff --check：通过
```

该检查点当时等待同一 reviewer 对上述修复和文档回写后的完整 fingerprint 做限定复审；
后续结果见第 19 节。全程未 commit、push、PR、deploy 或启用来源。

## 19. Django Admin 结构化地区边界的 RED/GREEN

同一 reviewer 对 fingerprint
`def49ae28389b8913ee5c86ee425094a0c136023921e7c6d2668fce766af5d9e`
限定复审时发现，运营 ModelForm 虽已收紧，但 Django `RaceEventAdmin` 仍从共享模型 choices
暴露五个 news-only 地区；同时本文顶部仍显示修复前计数。

只新增真实 `RaceEventAdmin(...).get_form(request)` 回归，旧实现结果为：

```text
Ran 1 test
FAILED (failures=2)
```

`other` 已可见，但 choices 不等于 `RACE_EVENT_FORM_REGIONS`，且五个 news-only 地区未被
排除。最小修复只在 `RaceEventAdmin.formfield_for_choice_field()` 复用同一受限集合，不改
模型 choices、采集或执行集合。修复后：

```text
RaceEventAdmin 精确回归：1/1
stable.test_new_region_news_sources：55/55
新地区 + 多地区归属 + 法国时间：155 passed / 1 existing skip
相邻来源、QQ、抓取、首页与旧爱尔兰合同：70/70
Django check：0 issues
makemigrations --check --dry-run：No changes detected
git diff --check：通过
```

同一 reviewer/native session 第三次限定复审已确认两项 finding 关闭，前后 fingerprint
`83675edc20358bf813a73a1db4ccf49e7f3f34bc67cd0b3ac4d05f4a57fb1353`
一致，结论 `VERDICT: APPROVED`，无 P0/P1/P2 actionable finding。所有来源和生产行为仍
关闭。

## 20. 第二批 date-only freshness 与复用来源测试计划

### TC-FRESH-001 date-only 当地日差边界

- 固定 `crawled_at`，分别构造来源当地发表日期日差 `0/1/2`。
- 断言 `0/1` 为 `candidate_date_within_one_day`，`2` 为
  `historical_date_outside_one_day`。
- 断言使用绝对日差，未来 1 天允许、未来 2 天拒绝。
- RED：当前没有可复用的 date-only 候选分类器。

### TC-FRESH-002 UTC 与来源当地日期边界

- 使用 `Europe/Dublin`、`America/Toronto`、`Asia/Dubai`、`Asia/Riyadh`、
  `Australia/Melbourne`。
- 构造 UTC 日期与来源当地日期不同的抓取时刻，断言只按来源当地 date 计算。
- Dublin/Toronto/Melbourne 覆盖夏令时，Dubai/Riyadh 覆盖固定 offset。
- RED：若直接比较 UTC date，至少一个子用例失败。

### TC-FRESH-003 date-only 午间规范化不得伪装精确时间

- evidence `precision=date` 且 `published_at` 为来源当地 12:00。
- 断言不会套用 6 小时小时级判断，输出日差与 date-only reason。
- verified 精确 `precision=minute`/`second` 返回 `precise_time_not_applicable`，既有 crawl
  行为不变。

### TC-FRESH-004 无效时区 fail closed

- evidence timezone 为空或非法。
- 断言分类器返回/抛出明确 `invalid_published_timezone`，crawl 单篇失败并继续，不回退
  Django/server timezone。
- 增加 `published_at`/`crawled_at` naive、时间为空、precision 缺失/未知、
  evidence/draft verified false；均为 `unresolved`，不得进入新五地区候选。
- 用 Sporting Life/Sky/BloodHorse 式“listing 临时 now + detail 无可信时间”fixture
  断言不得伪装成 Ireland/Canada 新稿。

### TC-FRESH-005 crawl 历史过滤

- fixture 混合 date-only 日差 1、日差 2、missing time、invalid timezone 和 precise time。
- 断言只 upsert日差 1 与 precise；`source_summary` 固定输出
  `candidate_date_within_one_day/historical_date_outside_one_day/
  precise_time_not_applicable/published_at_missing/freshness_unresolved`。
- 历史 skip reason 为
  `historical_date_outside_one_day`，不创建第二篇 `NewsArticle`。
- 断言两篇都不影响同轮其他详情处理。
- 全历史批次成功、无新增；全 unresolved 批次按稳定 `all_candidates_unresolved` 失败，
  不误报 `all_details_failed`。
- 历史稿不得产生 NewsSnapshot、术语发现、翻译、ranked revival 或 QQ 调用。

### TC-FRESH-006 probe 可复跑证据

- probe 使用固定 `crawled_at`，输出每篇 `candidate_status/reason/date_difference_days/
  source_timezone`，并聚合 candidate/historical 计数。
- 断言 probe 仍不写 `NewsSource/CrawlJob/NewsArticle/ProductionWindow`。
- 断言一次 probe/crawl 的全部文章共享同一个 aware `crawled_at`。

### TC-FRESH-007 判定证据与窗口摘要

- candidate 的 decision、固定 crawled_at、来源时区、发表/抓取当地日期和日差写入 article
  translation metadata 与 snapshot metadata。
- `crawl_news_source_task` 的成功窗口 payload 保存完整 `source_summary`；全 unresolved
  失败窗口同时保存 summary 和稳定 error category。

### TC-FRESH-008 pre-upsert target scope

- 同一个 canonical UK/US 来源提供一篇 Ireland/Canada 强事件稿和一篇普通 UK/US 稿。
- target 缺时间、无效时区、历史稿均在 `upsert_article_from_draft` spy 前停止；普通 UK/US
  缺时间稿完全保持旧行为并仍按旧路径进入 upsert。
- target freshness 合格稿把 `preview_content_scoped_region` result 随 draft 传入 upsert，
  断言正式 attribution 收到对象 identity 相同的不可变 result，preview mock 只调用一次。
- content-scoped allowlist 命中但 upsert 未传 preview 时，必须在任何文章/snapshot 副作用前
  以 `attribution_preview_required` fail closed，不允许 upsert 内补算。
- preview 与正式 attribution 引用同一 `EVENT_REGION_KEYWORDS`/边界匹配器；关键词增量只改一处。

### TC-ATT-012 爱尔兰/加拿大复用来源强信号

- 英国来源标题 `Irish Oaks` 必须得到 Ireland 主候选，不得退回 UK。
- 美国/全球来源标题含 `Woodbine Oaks` 或 Ontario 强证据时必须得到 Canada 主候选。
- 来源默认地区只作弱回退；现有 Ascot/Kentucky 负例继续通过。
- mode off + content-scoped 开关和 canonical source allowlist 启用时，Ireland/Canada 正例只写
  `review_candidate` 与人工地区门禁；同源普通 UK/US、无强证据稿不写候选、不加门禁。
- 同一 canonical 稿重复发现仍只有一篇 `NewsArticle`，不会因目标地区产生 wrapper 副本。

### TC-PERM-001 canonical 来源许可不可被 wrapper 放宽

- 同一 canonical source 的地区关键词 adapter/wrapper 继承 blocked/unknown permission。
- TDN、TDN France、TDN broad 和模拟别名均在 `fetch_listing` 前返回
  `permission_blocked_preflight`，mock request 调用为 0。
- 普通来源按 registry 返回；adapter 类字段与 registry 冲突时以 registry 为准。

### TC-BUDGET-001 unknown research 请求硬预算

- JCSA/Racing Victoria 各自 budget 为实际 HTTP transport GET：listing 1、detail 2；每次
  `session.get()` 前消费，不按 `_bounded_html()` 逻辑调用计数。
- 第 2 次 listing 或第 3 次 detail 在网络 mock 前抛 `source_request_budget_exhausted`。
- 一个详情失败仍消耗一次 attempt；两个来源 ledger 相互隔离。
- listing 首跳返回 redirect 时，第二跳在网络前因 listing 预算耗尽；实际 GET 恰为 1。
- detail 首跳 redirect 可完成第二跳并耗尽 detail 预算；第三跳或后续新 detail 在网络前停止。
- 失败 redirect/非 200 同样消费已发生的 hop；预算耗尽后 mock 调用数不再增加。
- unknown 且未实现 budget hook 的 Simple/多查询 adapter 返回
  `research_budget_unsupported`，网络调用 0。
- blocked budget 固定为 0/0。

### TC-PERM-002 crawl 与隔离 runner preflight

- 开启 production permission enforcement 的测试设置下，`_crawl_international_source()` 可先
  创建审计 CrawlJob，但必须在 adapter listing mock 前失败；CrawlJob 为 failed、error
  category 统一为 `permission_blocked_preflight`，请求 ledger 为 0，
  NewsArticle/NewsSnapshot/TranslationRun 为 0。
- probe 对 blocked source 输出 technical not-probed、permission blocked、effective blocked
  与 request ledger 0。
- source `enabled=true/production_approved=false` 不进入通用 poll，直接 crawl 也在网络前
  失败。flag 关闭 + blocked managed source + public/direct crawl 仍须
  `permission_blocked_preflight` 且网络调用 0；flag 只影响独立 scheduled task。
- 自动 poll 必须 dispatch 参数中没有 `origin/bypass` 的 scheduled task；public/direct task
  即使伪造 `window_id` 也不能进入 scheduled compatibility policy。

### TC-PERM-003 unknown 只做技术 probe

- unknown 来源只有显式 technical-probe 标志可按预算联网，默认 probe 与 production poll
  均不选择。
- 断言 unknown probe 不创建 `NewsArticle/CrawlJob/ProductionWindow`，不调用翻译。
- 机械翻译 smoke 使用自有合成文本/最小 fixture；结果不能冒充真实外部新闻翻译。

### TC-PERM-004 legacy 国际来源兼容

- 固定变更前全部 enabled + production-approved 国际来源快照；flag 关闭时断言 production
  poll 与 scheduled task 选择集合逐项完全相等，不只是非空，并输出
  `legacy_permission_unregistered`。
- 同一来源未获 production approval 时仍不选择；legacy compatibility 不等于
  `automation_permission_status=approved/effective eligible`。
- legacy 未登记来源不得进入 Ireland/Canada content-scoped candidate allowlist。
- registry completeness 断言 managed canonical 集合恰为五个首批 adapter 加 TDN canonical，
  所有 TDN 别名映射到同一项，普通 Sporting Life/Sky/France Galop/SCMP 等不因未登记被拦截。
- flag 开启的 scheduled 差异测试只允许显式 TDN canonical 家族被
  `permission_blocked_preflight` 阻断；关闭 flag 后恢复原自动选择集合。public/direct task
  在两种 flag 值下都阻断 blocked TDN 且请求为 0。

### TC-EVIDENCE-001 旧 TDN 证据隔离

- 第二批新 SQLite 从空库开始，blocked source NewsArticle、正文、HTML、TranslationRun 和
  请求均为 0。
- 第一批数据库仅作为“许可结论前历史探测”移动到仓库外私有 quarantine，不计入候选/翻译
  验收。

### 计划验证范围

```bash
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true \
python manage.py test \
  stable.test_new_region_news_sources \
  stable.test_multiregion_attribution_change \
  stable.test_france_news_freshness_change --noinput
```

本节新增行为必须先保存真实 RED；之前已经完成的第一批行为不补造历史 RED。

## 21. 第二批最终 GREEN 与真实 proof

### RED

```text
Ran 18 tests
FAILED (failures=41)
errors=0
```

失败来自缺少 date-only classifier、共享 attribution preview、canonical permission resolver、
固定 crawled_at、pre-upsert 过滤、source poll approval 和窗口 summary，不是 import/setup
或网络错误。

### 首轮 GREEN

```text
stable.test_new_region_news_sources_round2: 31/31
新地区 + 归属 + 法国时间 + 通用 poll: 202 passed / 1 existing skip
Django check: 0 issues
makemigrations --check --dry-run: No changes detected
git diff --check: pass
```

真实 technical probe 每源严格使用 listing `1`、detail `2`：

- JCSA：list `12`、detail/time `2/2`、artifact
  `75ecff06eb4b72dc04ae42ac138bf68f2177eaac587b8a32c35d568987eb5e24`；
- Racing Victoria：list `20`、detail/time `2/2`、artifact
  `58d1818b0ee31fac28777164724bf326bbf62c36cacb39bb9ff00322f8ad3566`。

两源 technical accepted、permission unknown、effective production blocked，最新样本均不在
六小时窗口。blocked 来源零请求；外部业务文章和全文翻译均为 0。合成 dummy smoke 为
`translated/pending_edit`，published/QQ 均为 0，不计作真实中文新闻翻译。

### 原生 review findings RED/GREEN

新增 3 个精确测试：

- production-window 在 flag false 时必须 dispatch scheduled task；
- 预算耗尽前一条 succeeded ledger 不得被改为 failed；
- redirect 次跳预算耗尽时前一条 redirected ledger 不得被改为 failed。

旧实现真实结果为 `34 tests / failures=3 / errors=0`。修复后：

```text
stable.test_new_region_news_sources_round2: 34/34
新地区 + 归属 + 法国时间 + 通用 poll: 205 passed / 1 existing skip
bounded HTTP + request budget: 10/10
Django check: 0 issues
makemigrations --check --dry-run: No changes detected
git diff --check: pass
```

### 第二批 RED 证据（2026-07-19）

专用离线测试文件：

- `server/stable/test_new_region_news_sources_round2.py`

执行命令：

```bash
cd server
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true \
python manage.py test stable.test_new_region_news_sources_round2 --noinput
```

测试建立后的首轮基线为 `Ran 18 tests`、`FAILED (failures=41)`；失败均为目标
assertion/subTest failure，Django system check 通过，没有 import、setup 或网络 `ERROR`。
在同一集成 worktree 补齐 transport-hop、scheduled policy、preview identity、canonical
UK/US missing-time 正负例和隔离副作用断言后，当时的完整 RED 窄测结果为：

```text
Ran 31 tests in 0.077s
FAILED (failures=3)
System check identified no issues (0 silenced).
```

当时三处真实 RED：

1. `stable.services.news_attribution.AttributionPreview` 尚不存在，无法证明命名的不可变 preview
   contract 及 preview → upsert → attribution 的对象 identity。
2. `probe_international_news_sources` 尚未接受显式 `research_mode`，无法执行 unknown、
   budget-unsupported、零业务写入的离线 probe contract。
3. `stable.tasks.crawl_scheduled_news_source_task` 尚不存在，无法证明 flag 关闭时自动选择集合
   逐项不变并只 dispatch 不暴露 `origin/bypass/policy` 的 scheduled task。

并行集成实现随后补上前两项；再次执行同一命令的当前结果为：

```text
Ran 31 tests in 0.080s
FAILED (failures=1)
System check identified no issues (0 silenced).
```

该次重跑仅剩第 3 项 scheduled task contract 为 RED；前两项已由相同测试转绿。两次完整窄测
都为 `0 errors`，没有 import/setup `ERROR`。后续 GREEN 回归见下一节。

本轮新增的 redirect/失败响应实际 GET 预算、listing `1`/detail `2`、预算耗尽后零额外 GET、
per-source ledger 隔离、blocked public/direct 两种 flag、伪造 `window_id`、TDN canonical
aliases、Ireland/Canada target 缺可信时间 pre-upsert 阻断、普通 UK/US 同源兼容、固定
freshness summary、全历史无 snapshot/术语/翻译/revival/QQ，以及新隔离库 blocked
文章/正文/HTML/TranslationRun/请求为 `0` 的测试替身，在上述最新集成快照已通过。这里仅记录
离线代码与测试替身证据；没有联网、读取旧 TDN 数据库、commit、push 或部署。

### 第二批 GREEN 与旧回归合同对齐证据（2026-07-19）

旧测试产生冲突的原因不是要放宽新安全合同，而是 fixture 仍表达许可 registry 落地前的行为：

- HRI 是 canonical blocked，旧 probe 却要求实际 fetch，并允许 adapter 自报
  `automation_permission_status=approved` 覆盖 registry；
- JCSA/Racing Victoria 是 canonical unknown，旧结构化 HTTP probe 未显式传入
  `research_mode` 和 transport budget；
- direct crawl/selector 正例 fixture 的 `production_approved=false`，却仍要求进入联网、
  HTTP 失败分类、due 或 stale-running 分支。

对齐时保留了原测试意图，并按以下边界修改 fixture/断言：

1. HRI 普通 probe 和伪造 approved adapter 都断言
   `permission_blocked_preflight`、`technical_status=not_probed`、request/listing `0`，registry
   始终胜过 adapter 自报。
2. JCSA/Racing Victoria 的结构化 403/429 技术 probe 显式使用 `research_mode=true`，mock
   transport 在 GET 前消费 listing budget，并断言 `request_count=1` 与单条 request ledger；
   probe 仍不写业务表。
3. 用于验证 empty listing、详情全失败、重复稿与 HTTP crawl 失败分类的 fixture 改为
   `production_approved=true`；这些 synthetic adapter 使用未登记的 fixture canonical，
   继续测试合法 legacy dispatcher 成功/失败路径，不绕过 managed permission。
4. `MultiRegionNewsProductionTests` 的 due/deferred/stale 正例明确设置
   `production_approved=true`；未批准来源被排除的安全断言未删除。

交接时旧 `stable.test_new_region_news_sources` 基线记录为 `55 tests / 8 failures / 3 errors`。
本测试所有者接手时并行修改已落入共享 worktree，首次立即复跑即为：

```text
Ran 55 tests in 0.295s
OK
```

`MultiRegionNewsProductionTests` 的两项旧 fixture 冲突在本轮实际复现为：

```text
Ran 16 tests in 0.888s
FAILED (failures=2)
```

为 due/deferred/stale 正例补齐 `production_approved=true` 后，精确子集结果：

```text
Ran 16 tests in 0.872s
OK
```

最终离线回归：

```text
stable.test_new_region_news_sources_round2
Ran 31 tests in 0.084s
OK

stable.test_multiregion_attribution_change
stable.test_france_news_freshness_change
Ran 100 tests in 0.434s
OK (skipped=1)

上述套件 + stable.test_new_region_news_sources
+ stable.tests.MultiRegionNewsProductionTests
Ran 202 tests in 1.706s
OK (skipped=1)
```

Django system check 均为 `0 silenced`，`git diff --check` 通过。所有验证均使用离线 fixture/mock；
没有真实网络请求、commit、push 或部署。

### 第二批 native review F1-F5 RED 证据（2026-07-19）

review 补测前先运行稳定基线：

```bash
cd server
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true \
python manage.py test stable.test_new_region_news_sources_round2 --noinput
```

基线结果为 `Ran 34 tests in 0.087s / OK`，确认 review 期间专用测试数已经从 31 漂移到 34，
且没有 import/setup error。

仅在 `stable.test_new_region_news_sources_round2` 增加 F1-F5 最小离线测试后，同一命令结果：

```text
Ran 41 tests in 0.105s
FAILED (failures=12)
System check identified no issues (0 silenced).
```

全部 12 项均为目标 assertion/subTest failure，`0 errors`。按 finding 对应如下：

- **F1（4 failures）**
  - production-window scheduler 实际 dispatch 参数为
    `(crawl_scheduled_news_source_task, source_id)`，缺少已 claim 的精确 `window_id`；
  - `crawl_scheduled_news_source_task(source_id, window_id)` 的成功、失败、flag-off TDN
    compatibility 三条路径均以“takes 1 positional argument but 2 were given”进入显式
    `self.fail`；
  - 新测试同时锁定：成功窗口必须保存完整 `source_summary`，失败窗口必须保存稳定
    `error_category/source_summary`，不得用“查找最新 RUNNING window”代替显式 window；flag-off
    TDN scheduled policy 可兼容运行，但同源 public/direct 仍须
    `permission_blocked_preflight`、零 fetch。
- **F2（4 subTest failures）**
  - 伪造的 metadata high-confidence preview 被重新构造并接受，没有抛
    `attribution_preview_required`；
  - `download_image` 已调用 1 次，并已经创建 1 条 `NewsArticle` 与 1 条 `NewsSnapshot`；
  - 新合同要求 allowlisted upsert 缺显式 `AttributionPreview` 时，在上述任何副作用前
    fail closed，metadata 只能作为审计输出，不能作为输入恢复对象。
- **F3（1 failure）**
  - 两个真实 detail 解析异常的 `all_details_failed` CrawlJob 实际 `fail_count=0`，预期为
    `2`；证明异常收口仍错误复用了 `seen_count`。
- **F4（0 failure，3 个回归场景均 GREEN）**
  - review 前已经存在 succeeded/redirected ledger 保持测试；本轮补充 failed-terminal 后再次
    consume 的场景；
  - 三条均通过：预算耗尽没有产生新 transport hop 时，ledger 长度不变，上一条
    `succeeded/failed/redirected` 状态均未被改写。该 finding 在当前基线已修复，本轮测试负责
    防回归，没有为追求 RED 制造假失败。
- **F5（3 subTest failures）**
  - 构造后修改原始 nested list 会污染 preview evidence；
  - preview 内嵌 dict 仍可新增字段、内嵌 list 仍可 append；
  - `related_regions` 已为 tuple 的既有断言通过，但 evidence 仍只是浅层
    `MappingProxyType`，未满足深不可变。

本轮只运行 Django SQLite 测试与内存 mock；没有网络访问、没有读取或修改隔离数据库，也没有
commit、push 或部署。

### F2 旧测试显式 preview 补救 GREEN（2026-07-19）

F2 fail-closed 实现完成后，旧
`ContentScopedPreviewTests.test_mode_off_uses_shared_preview_only_for_strong_target_and_dedupes`
仍把 preview 只序列化进 `draft.metadata`，与“不得从 metadata 重建 preview”的新合同冲突。
本次仅修正该测试：

- positive upsert 显式传入 `positive_preview`；
- negative upsert 显式传入 `negative_preview`；
- duplicate upsert 复用同一个 `positive_preview` 对象；
- 从 positive/negative draft fixture 移除 metadata preview，不再保留隐式恢复路径；
- 原 Ireland 正候选、普通 UK 负例、人工门禁与两篇文章 dedupe 断言全部保留；
- forged high-confidence metadata 必须在图片/文件/Article/Snapshot 副作用前失败的 F2 安全
  测试保留并通过。

精确旧测试：

```text
Ran 1 test in 0.016s
OK
```

最终 round2：

```text
Ran 41 tests in 0.139s
OK
System check identified no issues (0 silenced).
```

完整指定组合
`stable.test_new_region_news_sources + stable.test_new_region_news_sources_round2 +
stable.test_multiregion_attribution_change + stable.test_france_news_freshness_change +
stable.tests.MultiRegionNewsProductionTests`：

```text
Ran 212 tests in 1.904s
OK (skipped=1)
System check identified no issues (0 silenced).
```

`git diff --check` 通过；全部验证使用 SQLite 与离线 fixture/mock，没有网络访问、隔离数据库
操作、commit、push 或部署。

### F2 fake preview 类型限定 RED（2026-07-19）

开始前确认 `server/stable/test_new_region_news_sources_round2.py` SHA-256 为：

```text
aa012712f71a24eac664e8ae1de8b7c46a2d6d4f72bed8c98bde5d12642bb581
```

同一基线的 round2 结果：

```text
Ran 42 tests in 0.157s
OK
System check identified no issues (0 silenced).
```

本次只补 F2 类型限定：

- 合法 ordinary UK/US ingestion 路径不再用 `_FrozenPreviewFixture` 冒充，改为构造真实
  `AttributionPreview`；
- 新增一个 `Mock(spec=AttributionPreview)` fake。它可伪造 `__class__` 并通过浅层
  `isinstance`，同时提供 Ireland target、confidence `100`、伪造 evidence/status/reason 等
  字段；
- allowlisted upsert 必须识别它不是真实 preview，并在图片下载、文件副作用、Article 与
  Snapshot 写入前抛 `attribution_preview_required`。

新增测试后的专用结果：

```text
Ran 43 tests in 0.153s
FAILED (failures=4)
System check identified no issues (0 silenced).
```

四项均来自同一个目标测试的 subTest assertion，`0 errors`：

1. 没有抛出 `attribution_preview_required`；
2. `download_image` 被调用 1 次；
3. `NewsArticle` 实际写入 1 条；
4. `NewsSnapshot` 实际写入 1 条。

现实现的 `isinstance(attribution_preview, AttributionPreview)` 可被带伪造 `__class__` 的 mock
绕过，因此该 RED 要求使用不能被 proxy/spec 冒充的真实对象边界。测试只使用 SQLite 与离线
mock，没有网络访问、隔离数据库操作、commit、push 或部署。

最小修复后在副作用前以 exact type identity 验证真实类边界，`None`、普通 fake 和
`Mock(spec=AttributionPreview)` 均返回 `attribution_preview_required`；合法 ingestion
fixture 使用真实 `AttributionPreview`。独立最终验证：

```text
stable.test_new_region_news_sources_round2
Ran 43 tests
OK

完整指定组合
Ran 214 tests
OK (skipped=1)

bounded HTTP + request budget
Ran 11 tests
OK

Django check: 0 issues
makemigrations --check --dry-run: No changes detected
git diff --check: pass
```

### F1 启动前窗口绑定 post-fix GREEN regression（2026-07-19）

根任务复核 F1 修复后发现，`crawl_scheduled_news_source_task(source_id, window_id)` 的显式
窗口绑定校验已经先于本测试落地，无法取得真实 RED。本次没有反向破坏代码制造失败，也没有
补写虚构 RED；这是一项如实记录的 procedural gap，并以一个测试、四个 subTest 增加
post-fix GREEN regression：

- `window_id` 不存在；
- window 属于其他 source；
- window kind 不是 `CRAWL`；
- window status 不是 `RUNNING`。

四种输入均稳定失败为 `invalid_scheduled_crawl_window`，并且发生在
`sync_builtin_sources`、task log、crawl core、来源健康记录和窗口写回之前。测试同时比较
全部窗口与来源健康字段的前后快照，证明无效绑定不修改任一窗口或来源，也不创建 CrawlJob。
`window_id=None` 的 generic poll 兼容路径继续由既有自动选择与 scheduled dispatch 测试覆盖。

真实验证结果：

```text
stable.test_new_region_news_sources_round2
Ran 42 tests in 0.161s
OK

stable.test_new_region_news_sources
+ stable.test_new_region_news_sources_round2
+ stable.test_multiregion_attribution_change
+ stable.test_france_news_freshness_change
+ stable.tests.MultiRegionNewsProductionTests
Ran 213 tests in 2.367s
OK (skipped=1)

stable.test_new_region_news_sources.NewRegionBoundedHttpTests
+ stable.test_new_region_news_sources_round2.SourceRequestBudgetTransportTests
Ran 11 tests in 0.008s
OK

Django check: System check identified no issues (0 silenced).
makemigrations --check --dry-run: No changes detected
git diff --check: pass
```

F1-F5 当前代码修复、F2 exact type identity 加固和上述补充回归仍须交回同一
reviewer/session 做限定复审；本节不表示 review 已通过。验证仅使用 SQLite 与离线
fixture/mock，没有网络访问、隔离数据库操作、commit、push 或部署。

### reviewer F2 exact Preview/Result 类型集合 RED（2026-07-19）

native same-session `019f79aa-be0a-71c0-8399-bff0c36ff038` 对 fingerprint
`13f7e095…6422`（HEAD `42a06f47`、content `60743f…78d0`）执行只读限定复审，命令 exit
`0` 且前后一致，但结论为 `VERDICT: REVISE`。F1/F3/F4/F5 已 `CLOSED`；唯一 P1/F2 指出
content-scoped attribution 的合法真实输入合同是 exact type 属于
`{AttributionPreview, AttributionResult}`，不能把 ingestion 收窄为只接受 Preview；同时
direct `apply_article_attribution` 也必须拒绝可伪造 `isinstance` 的 fake Preview/Result。
本次严格测试先行，只修改 round2 测试与本证据后取得下述真实 RED。

新增两个最小测试：

1. allowlisted ingestion/upsert 传入 exact real `AttributionResult`，要求正常创建文章并保存
   Ireland `review_candidate`；当前实现因只接受 exact Preview 而错误抛出
   `attribution_preview_required`。
2. direct `apply_article_attribution` 分别传入 `Mock(spec=AttributionPreview)` 与
   `Mock(spec=AttributionResult)`；两个 fake 均可伪造 `isinstance`，但合同要求在调用
   `_save_content_scoped_review_candidate`、`article.save` 或修改内存/数据库 attribution
   字段前稳定抛出 `attribution_preview_required`。

已有
`test_non_none_fake_preview_is_rejected_before_side_effects` 保留并继续 GREEN，证明 ingestion
fake Preview 负例没有被新正例放宽；非 allowlist 和旧行为范围未扩大。

执行命令：

```bash
cd server
PATH="/Users/mentianlu/Code/umanews/.venv/bin:$PATH" \
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true \
python manage.py test stable.test_new_region_news_sources_round2 --noinput
```

真实 RED：

```text
Ran 45 tests in 0.224s
FAILED (failures=9)
System check identified no issues (0 silenced).
```

9 个失败全部来自新增目标 assertion/subTest，`0 errors`：

- exact real `AttributionResult` ingestion 正例：`1` 个 failure，当前错误返回
  `ValueError('attribution_preview_required')`；
- direct fake Preview：`4` 个 subTest failures，分别为未抛门禁、candidate save helper
  被调用、`article.save` 被调用、内存与数据库字段被修改；
- direct fake Result：同样 `4` 个 subTest failures。

这组 RED 精确锁定“只接受 exact Preview/Result，拒绝其余对象”的 reviewer finding；没有
fixture/import/setup error，没有联网、commit、push 或部署。按任务要求停在 RED，不修
runtime，也不更新 current_state/status/rollout/tasks。

最小修复后：

- allowlisted `upsert_article_from_draft` 接受 exact real
  `{AttributionPreview, AttributionResult}`；
- direct `apply_article_attribution` 在 candidate helper、`article.save` 及任何内存/数据库
  attribution 字段变更前执行相同 exact-type 门禁；
- `Mock(spec=...)`、子类和其他对象统一 fail closed 为
  `attribution_preview_required`；
- 非 content-scoped legacy 路径保持不变。

根任务独立复核：

```text
stable.test_new_region_news_sources_round2
Ran 45 tests
OK

stable.test_new_region_news_sources
+ stable.test_new_region_news_sources_round2
+ stable.test_multiregion_attribution_change
+ stable.test_france_news_freshness_change
+ stable.tests.MultiRegionNewsProductionTests
Ran 216 tests in 2.247s
OK (skipped=1)

bounded HTTP + request budget
Ran 11 tests
OK

Django check: 0 issues
makemigrations --check --dry-run: No changes detected
git diff --check: pass
```

验证仍只使用 SQLite 与离线 fixture/mock，没有网络访问、隔离数据库操作、commit、push 或
部署；这些结果作为下述 F2-only 限定复审的既有测试证据。

### F2-only 最终原生限定复审证据（2026-07-19）

- same native session：`019f79aa-be0a-71c0-8399-bff0c36ff038`；
- 命令模式：`codex exec resume -c 'sandbox_mode="read-only"' ...`；
- 内层 sandbox：read-only；命令 exit：`0`；
- 限定范围：仅复审 ingestion 与 direct apply 的 exact type
  `{AttributionPreview, AttributionResult}` 合同及 fake/`None` 副作用前拒绝；
- actionable findings：无；F2：`CLOSED`；
- 结合上轮 F1/F3/F4/F5 均 `CLOSED`，最终结论：`VERDICT: APPROVED`。

审前与审后 helper raw 完全一致：

```text
fingerprint=30e7592accad91458fc2f9609f107232221e3bbd5295345e2b0b5bf060b6ca1c
HEAD=42a06f47c7529f2b9ca23b01ad951d8ab10e304d
content=a1dc620e46956375e3b188d6897bf408c7540d84c65f6f72c23ef6e5b284a636
tracked=5bd6b4393d8a6ee833e5118abd9c8603ff58888c9e497124009aea124e8a893d
untracked=af9c1ea5e1432c5a7b904c5f0009ba969b6753433a003b4aa6618cf106dff04d
```

native reviewer 遵令未重跑 Django 测试；结论引用复审前由根任务独立取得的专用 `45/45`、
完整指定组合 `Ran 216 tests / OK (skipped=1)`、bounded HTTP + request budget `11/11`，
以及 Django check、migration `No changes detected`、`git diff --check` 通过证据。

review 期间没有编辑、联网、commit、push、PR、deploy 或启用来源。本段 docs-only 证据回写
会改变最终 fingerprint，因此仍须对最终 docs-only fingerprint 做一致性复审，并等待用户对
最终冻结内容的新授权；历史用户授权不可复用。

## 22. 内部使用与第三批多来源测试计划

以下保留实施前测试计划；这些目标后来已经按测试先行完成，真实 RED 与最终 GREEN 汇总见
第 23 节。较早历史 GREEN 没有替代本轮 RED。

### TC-INT-001 匿名 HTML 全站门禁

- `SITE_INTERNAL_ONLY_ENABLED=true` 时，新闻、文章、赛事、马匹、sitemap 和 console 入口的
  匿名请求不返回业务正文，统一跳转登录并保留站内 `next`。
- 已认证请求保持原 view 行为。
- login/logout、Django admin login 无重定向循环。

### TC-INT-002 API 与健康检查

- 匿名 `/api/...` 返回 JSON `401`，不泄露文章或翻译字段。
- `/healthz/` 无认证保持 200；静态资源保持可读取。
- 配置关闭时保留变更前匿名页面行为，作为紧急兼容回滚，但生产默认值断言为 true。

### TC-INT-003 robots 与 sitemap

- 内部模式 `robots.txt` 返回 `Disallow: /`。
- 匿名 sitemap 不返回 URL 清单；认证请求可用于内部验收。

### TC-INT-004 受保护媒体与 HTTPS 预检

- Nginx config 不存在公开 `/media/ alias`；`/protected-media/` 必须标记 internal。
- 匿名 media 请求不返回文件；认证 local-media 请求返回安全 X-Accel-Redirect/FileResponse。
- `..`、绝对路径、symlink、目录和不存在文件均拒绝。
- 内部模式 + OSS 在未配置 private bucket/签名 helper 时启动预检失败；合法私有签名 URL
  具有短 TTL，不泄露 bucket credential。
- `DEBUG=false` 必须同时启用 secure session/CSRF cookies；direct
  `SECURE_SSL_REDIRECT=true` 可通过，可信反代仅在 trusted termination flag 与合法
  `SECURE_PROXY_SSL_HEADER=(HTTP_*, https)` 同时存在时通过。缺 TLS 合同、缺 proxy header
  或 cookie 不安全均拒绝启动。

### TC-DIST-001 QQ 和外部分发硬门

- 内部模式下，delivery 创建、单篇 push、窗口 push 和 URL check 均在副作用前返回
  `internal_only_distribution_blocked`。
- OneBot mock、HTTP mock、`QQPushDelivery.objects.create`、`PushLog.objects.create` 均为
  0 次。
- 全局站点门显式关闭时，来源级 `internal_only/public-false` 稿件仍不出现在公开列表/详情，
  QQ 使用同一文章级 blocker 拒绝。
- 文章相关 `send_mail`/QQ 通知只能收到 sanitizer 白名单 payload；测试注入标题、正文、
  译文、摘要和来源 URL，断言邮件/QQ 参数均不包含这些值。无法生成安全摘要时 `send_mail`
  和 OneBot 调用均为 0；文章级失败通知只允许 `article_id`。
- 历史 SENT/FAILED delivery 不被批量修改。

### TC-PERM-005 新技术准入三轴

- registry accepted 产生 `allowed=true`、`usage_scope=internal_only`、
  `public_publish_allowed=false`；blocked 在 request spy 前停止。
- host mismatch、403、429、challenge、login/paywall 和 robots disallow 均 fail closed。
- HRI/Woodbine/ERA/JCSA/Racing Victoria 按当前技术证据映射到内部使用口径；旧 terms 文本只
  进入 `terms_risk`，不能显示“来源已授权”。
- `production_approved` 仍为独立 false，sync 不自动开启。

### TC-RSS-001 RSS/Atom 合同

- RSS 2.0、Atom、RFC 2822、ISO 8601、GUID/link 去重、20 条上限、非法 XML、空 feed、
  错误 content type、跨 host redirect 和 2 MiB 上限分别覆盖。
- 不读取 enclosure/media；所有 draft `images=[]`。
- feed 精确时间优先；只有日期时进入既有 date-only classifier。

### TC-SRC3-001 十二来源身份与默认状态

- 12 个新 `SourceSite`、adapter 和 `NewsSource` 行一一对应。
- 每个来源 `enabled=false/production_approved=false`，地区、语言、kind、timezone、
  homepage/feed、host allowlist 和 interval 正确。
- sync 二次执行不覆盖运行态字段。

### TC-SRC3-002 十二来源离线 fixture

- 每源至少一个 listing 和一个 detail 最小 fixture，验证 canonical URL、标题、正文、
  时间 evidence 和地区。
- IrishRacing/Canadian Thoroughbred 覆盖 date-only 日差 0/1/2。
- JHR 排除 tips/odds；Tasracing 排除 harness/greyhound；SPA 排除 camel/show jumping。
- 全部 fixture 不包含完整第三方文章，只保存最小结构和自有短文本。

### TC-SRC3-003 crawl 集成

- 每地区至少两个来源通过 adapter -> freshness -> attribution preview -> upsert；
  重复 URL 只产生一个 article。
- 历史/date unresolved 在 upsert 前停止；单篇 detail 失败不阻断同轮；全部失败状态稳定。
- 来源关闭、未 production approved、未 allowlist、backoff 或 technical blocked 均不联网。

### TC-TRANS-001 外部翻译处理开关

- 默认 false 时远程 provider 在调用 spy 前返回 `external_translation_disabled`，文章保持
  待翻译且抓取结果不回滚。
- 自动改写链和直接 rewrite task 同样在 client spy 前返回 `external_rewrite_disabled`；
  translation/rewrite 两类 remote client 调用均为 0。
- 本地 provider 可运行；显式 true 时沿用既有远程 translation/rewrite provider。
- dummy 不得在汇总中计为真实中文翻译。

### TC-MIG-001 第三轮主线 migration 集成与当前重验门禁

- 第二轮 `origin/main@58f00961…` 的 `0047_race_live_public_beta_controls` 与本 change 现有 `0047`
  先汇入 `0048_merge_20260719_2242.py`，再应用
  `0049_alter_newsarticle_source_site_and_more.py`。
- main 新增 `0048_raceeventrunner_external_runner_identity.py` 后，由无操作
  `0050_merge_20260720_0017.py` 与功能 `0049` 汇合；断言 `0050` 为唯一 leaf。
- `makemigrations --check --dry-run` 无漂移；race-live 与新闻 choices 均保留。
- `migrate --plan` 与隔离测试库 migrate 必须通过；临时 PostgreSQL 正向/反向/再次正向验证
  仍是发布前未完成项。
- 当前已重新集成 `origin/main@a122ff6d…`；必须重验 migration leaf，不能直接继承第二轮
  `0050` 唯一 leaf 结论。

### 计划 RED/GREEN 命令

```bash
cd server
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true \
python manage.py test stable.test_internal_news_access \
  stable.test_new_region_news_sources_v3 --noinput
```

实现后还需运行既有新地区两份测试、QQ、公开 views/API、source polling、translation、
race-live choices 直接回归；真实网络只允许在测试全部 GREEN 和代码 review 之前执行独立
低预算 probe，自动化测试禁止联网。

## 23. 首次 main 无提交集成证据（历史）

### 第三批 RED

在只包含测试与测试证据、目标运行时尚未实现时，聚焦范围结果为：

```text
62 tests
74 expected failures
0 errors
```

失败覆盖匿名访问、媒体、外发、外部 AI 门禁、12 源 registry/adapter/fixture/crawl、日期
精度和 migration 集成；没有使用 import/fixture/environment error 冒充 RED。

### 最终 GREEN 与回归

```text
内部访问 / media / 外发 / AI 门禁：47/47
重点功能独立复核：175/175
race-live 集成回归：37/37 + 63/63
manage.py check：通过
makemigrations --check：无漂移
migrate --plan：可解析
git diff --check：通过
cached diff check：通过
```

测试维护严格限于测试环境兼容：旧匿名页面测试显式覆盖
`SITE_INTERNAL_ONLY_ENABLED=false`，需要进入生产来源选择路径的 fixture 显式补
`production_approved=true`。这两项都没有修改生产默认：
`SITE_INTERNAL_ONLY_ENABLED=true`、新来源
`enabled=false / production_approved=false` 及所有外发 fail-closed 门禁保持不变。

### 当时尚未验证与第三轮更新

- 当时尚未在 main-integrated worktree 对 12 个第三批来源做最终受控真实抓取；该事项在
  final-integrated 仍未完成。
- 尚未使用真实外部翻译 provider 对受控候选做翻译实跑。
- 尚未完成 PostgreSQL 专用 migration、并发或生产形状验证。
- 当时尚未完成独立代码审核；该审核后续产生七项 finding，见第 24 节。用户新授权和
  commit/push/PR/deploy 仍未完成。

因此 `47/47`、`175/175` 和 race-live 回归只证明本地 SQLite/fixture 集成，不代表来源可生产
调度或生产环境已内部化。

## 24. 首次独立代码审核 finding 与最终 main 二次集成

### 审核结论与真实 RED

首次独立代码审核结论为 `REVISE`，包含 `2 P1 + 5 P2`。只增加七个 finding 聚焦测试后，
真实结果为：

```text
7 tests
7 failures
0 errors
```

七项分别锁定：

1. 来源级 `internal_only/public_publish_allowed=false` 在全局站点门关闭时仍阻断公开
   queryset、详情和 QQ；
2. `DEBUG=false` 内部模式要求 secure cookies，并要求 direct HTTPS 或显式可信 TLS 反代合同；
3. 外部 AI 关闭时 retry selector 在 claim 前跳过，preclaim 兼容状态被释放；
4. 通知 sanitizer 保留安全 counts/IDs，同时删除内容与来源 URL；
5. batch translation 的 gated skip 不计为 translated；
6. TDN listing 的 stale/missing-time skip 恢复计入 freshness summary；
7. probe 在 accept/reject 前调用正式 canonical normalize，并保留时间/主题拒绝原因。

### 修复 GREEN

七项均已最小修复，聚焦测试 `7/7`。旧 translation retry 耗尽通知测试同步改为安全
`article_id`-only 断言，不再期待或容许来源 URL。额外回归：

```text
重点功能：175/175
translation failure recovery：22/22
latest-main release-gate：69 OK
SQLite skipped PostgreSQL-only：15
race-live：37/37 + 63/63
migration check / plan / test DB migrate：通过
Django checks / git diff --check / cached diff check：通过
相关 py_compile：通过
```

### 审核完整性边界

同一 reviewer session 对七项修复范围实质确认 actionable findings 清零并给出
`APPROVED`，但审查期间 main 漂移，因此完整性结论为 `BLOCKED`。随后已把候选二次集成到
`origin/main=HEAD=58f00961f2cd9750d1285f7d6229494903e975a5`，并用无操作
`0050_merge_20260720_0017.py` 合并 main `0048` 与功能 `0049`。最终精确版本尚未复审，
本节不得作为成功代码 review 或发布授权依据。第三轮已经重新集成
`origin/main=HEAD=a122ff6dde16ab4b53f34e446b0f959751ad7a77`，`origin/main..HEAD=0`，
但仍须送同一 reviewer 复审。

### 当前剩余边界

- 当前最新 main 候选的最终精确版本同 reviewer 复审。
- 真实中文远程翻译仍未完成；第三轮 dummy 编排不替代远程 provider 验收。
- PostgreSQL 专项与生产 TLS/私有 media 验收。
- 用户新授权、commit、push、PR、deploy。
