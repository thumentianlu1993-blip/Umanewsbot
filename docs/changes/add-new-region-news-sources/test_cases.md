# 新地区新闻抓取测试用例

## 文档状态

- 阶段：已写 `55` 个专用自动化测试；多轮补救与代码审查 RED 均已最小修复，当前专用
  `55/55`、直接组合 `155` 个通过加 `1` 个既有 skip、相邻回归 `70/70`。本文后续
  `51/51`、`151`、`69/69` 是当时历史检查点，不代表当前摘要
- RED 要求：新增运行时行为先观察因目标能力未实现而失败；本 change 的历史证据保留在本文
- CI 网络：禁止；适配器测试只使用最小 HTML/JSON fixture
- 真实网络：仅手动只读 probe，独立于自动化 GREEN

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
