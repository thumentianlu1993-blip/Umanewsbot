# 新地区新闻抓取规格

## 文档状态

- 专项：爱尔兰、加拿大、阿联酋、沙特阿拉伯、澳大利亚新闻抓取
- 当前集成基线与 HEAD：`a122ff6dde16ab4b53f34e446b0f959751ad7a77`
- 当前分支：`codex/add-new-region-news-sources-release-candidate`
- 当前 worktree：
  `/Users/mentianlu/Code/umanews/.worktrees/add-new-region-news-sources-release-candidate`
- main 对齐：第三次集成时 `origin/main=HEAD`，`origin/main..HEAD=0`。此前
  integrated/main-integrated/final-integrated 三个 worktree 只作为回退副本。
- 阶段：方案独立审核已 `VERDICT: APPROVED`；首次独立代码审核为
  `REVISE (2 P1 + 5 P2)`，七项 finding 已按真实 RED 修复，但同一 reviewer 的修复复审因
  main 漂移而完整性 `BLOCKED`。当前已重新集成最新 main，仍须由同一 reviewer 复审最终
  精确版本，不得写成最终审核通过。项目后续只使用仓库原生流程，不再使用 OpenSpec。
- 生产状态：当前集成变更未 commit、push、创建 PR 或 deploy，migration 未在生产应用，
  未启用任何新来源。生产 HTTPS/获准 TLS 与私有媒体前置也尚未满足。
- 真实网络状态：已在迁移后的仓库外 `/tmp` SQLite 上完成透明、小预算、零生产写入的
  24-source live probe；技术结果为 `16 accepted / 8 blocked`。同库已用真实 RTÉ 正文和
  dummy provider 验证翻译任务/持久化编排，但未验证真实中文远程模型。
- 文档核对日期：2026-07-20

## 2026-07-20 第三轮受控 live evidence

- 探针使用已迁移的仓库外 `/tmp` SQLite、透明 bounded HTTP 和每源列表 `1` 次/详情最多
  `2` 次预算，不连接或写入生产。首次空库的 `no such table` 只属于探针环境错误；应用迁移
  后重跑，不能计作来源 blocked。
- 24-source technical registry 最终为 `16 accepted / 8 blocked`，全部固定
  `usage_scope=internal_only / public_publish_allowed=false`：
  - accepted：`rte_racing`、`irishracing_news`、`dubai_racing_club`、`jcsa_news`、
    `spa_horse_racing`、`racing_victoria_news`、`just_horse_racing`、`the_straight`、
    `racing_nsw_news`、`tasracing_news`、`tdn`、`bloodhorse`、
    `horse_racing_nation`、`sky_sports_racing`、`sporting_life`、`bha`；
  - blocked：`hri_news`、`woodbine_news`、`canadian_thoroughbred`、
    `assiniboia_downs_news`、`emirates_racing_authority`、`the_national_racing`、
    `arab_news_racing`、`paulick_report`。
- 第三批 12 源自身为 `8 accepted / 4 blocked`；四个 blocked 是 Canadian Thoroughbred、
  Assiniboia Downs、The National、Arab News。IrishRacing、SPA、Racing NSW、Tasracing
  均依据 live 页面结构完成 TDD 修复并复探 accepted。Racing NSW 额外排除 tips/preview，
  generic `Latest News` 不得覆盖 RSS 标题。
- HRI、Woodbine、ERA listing 虽为 HTTP `200`，但端到端详情均因
  `missing_published_at` fail closed，故仍为 technical blocked。TDN 正文端到端成功后改为
  accepted，但该样本时间 evidence 为 unverified，不能进入 freshness 候选。JCSA、Racing
  Victoria 的 live 结果为 accepted。
- 综合来源可复用的 internal-only 技术池为 TDN、BloodHorse、Horse Racing Nation、
  Sky Sports Racing、Sporting Life、BHA。离线归属测试确认 Curragh/Irish Oaks 稿归
  Ireland，Woodbine/Canadian 稿归 Canada；无强关键词时保留来源原有 US/UK 地区。
  Sporting Life technical accepted，但当前样本时间 unverified，候选状态 deferred。
- 最新精确 probe 时点约为 `2026-07-19T17:41Z`，严格最近六小时窗口约为
  `11:41Z..17:41Z`。可信候选只有 Ireland `2`：
  - RTÉ：`Power Blue back to winning ways at the Curragh`，
    `2026-07-19T15:09:15Z`，verified；
  - IrishRacing：`Tokyo Tower shows resolution to land Curragh finale`，
    `2026-07-19T16:51:00Z`，verified。
  Canada/UAE/Saudi/Australia 均为 `0`。TDN `17:28:05Z` 因 unverified 不计；Just Horse
  Racing `10:09:13Z` 超过六小时不计；DRC `07-09`、JCSA `03-22`、SPA `01-07`、Racing
  Victoria `07-15`、The Straight `07-17`、Racing NSW `07:32`、Tasracing `07-03`
  均不计。本轮样本均有精确时间，没有使用 date-only `0/1` 日兜底提高数量。
- 同一迁移临时库以真实 RTÉ 正文 `6616` 字符运行
  `TRANSLATION_PROVIDER=dummy`；外部 AI 默认门保持关闭。
  `translate_article_task` 返回 `translated=true`，文章为 `translated`，
  `TranslationRun=success`，标题明确带 `[未配置真实翻译模型]`。本机
  `SILICONFLOW`/`OPENAI` key 均 absent，因此只证明任务与持久化编排通过，真实中文远程模型
  尚未验证。
- 最新 release-candidate 离线组合为 `214/214 OK`，follow-up 为 `10/10`；migration 无漂移、Django
  checks 通过。来源实现代理另报告 `202` 组合加 `1 skip`、translation recovery `22/22`；
  这些计数按各自测试集合保留，不互相替代。
- 所有第三批 source definition 继续
  `enabled=false / production_approved=false`。live probe 和 dummy 翻译编排已完成；真实
  远程翻译、最终 reviewer、PostgreSQL 专项、生产 TLS/私有 media、用户
  新授权、commit/push/PR/deploy 仍未完成。

本节是当前事实，优先于下方第二轮“尚未 live probe”的历史检查点。

## 2026-07-20 第二轮最终主线无提交候选（历史检查点）

- 方案独立审核已通过；第三批运行时 RED 基线为
  `62 tests / 74 expected failures / 0 errors`，失败来自目标行为尚未实现。
- 首次独立代码审核提出 `2 P1 + 5 P2`。七项聚焦测试先得到
  `7 failures / 0 errors`，修复后 `7/7`：来源级 internal-only/public-false 独立阻断公开
  queryset/详情/QQ；生产内部模式 secure cookies 与 direct HTTPS/可信 TLS 反代二选一合同；
  translation retry/preclaim/batch skip 语义；通知安全 counts/IDs 和 URL 清除；TDN freshness
  metrics；probe canonical normalize/时间/主题拒绝。
- 默认配置固定为 `SITE_INTERNAL_ONLY_ENABLED=true`、
  `NEWS_EXTERNAL_AI_PROCESSING_ENABLED=false`。`DEBUG=false` 时 session/CSRF secure cookies
  是硬门；传输层必须 direct `SECURE_SSL_REDIRECT=true`，或显式
  `SITE_INTERNAL_ONLY_TRUSTED_TLS_TERMINATION=true` 且有合法
  `SECURE_PROXY_SSL_HEADER` HTTPS 合同。认证 local media 或私有 OSS 短期签名仍是生产前置。
- 第三批 12 个来源已经按本文设计清单实现，全部同步为
  `enabled=false / production_approved=false`。Google News discovery 明确排除在本批之外。
  既有 HRI、Woodbine、ERA 保持 technical blocked，JCSA、Racing Victoria 保持 unknown；
  未经新的受控探测不得擅自改为 accepted。
- 日期精度最终合同为：可信本地发表日期与本地抓取日期相差 `0/1` 天进入候选，`>1` 天记为
  历史；缺少可信时间、precision/evidence 不完整或时区无效时记为 `unresolved`，在 upsert
  前停止。
- migration DAG 保留两个 `0047`；功能路径经
  `0048_merge_20260719_2242.py -> 0049_alter_newsarticle_source_site_and_more.py`，
  main 路径为 `0048_raceeventrunner_external_runner_identity.py`，最终由无操作
  `0050_merge_20260720_0017.py` 汇合为唯一 leaf。migration check、plan 和测试库 migrate
  通过；PostgreSQL 专项仍未完成。
- 最新验证为 findings `7/7`、重点功能 `175/175`、translation failure recovery `22/22`、
  latest-main release-gate `69 OK`（SQLite 跳过 PostgreSQL 专项 `15`）、race-live
  `37/37 + 63/63`；Django/migration checks、diff/cached diff 和相关 `py_compile` 通过。
  旧 URL 通知测试已改为安全 `article_id`-only 合同。
- 同一 reviewer session 对七项修复的实质判断为 `APPROVED`，但完整性结论仍因 main 漂移为
  `BLOCKED`。二次集成到 `58f00961…` 后尚未完成精确版本复审；旧审核与旧授权均不覆盖。
- 仍未完成：12 源受控 live probe、最近 6 小时汇总、真实翻译实跑、PostgreSQL 专项、最终
  精确版本复审、生产 TLS/私有 media、用户新授权及 commit/push/PR/deploy。所有新来源仍不可
  生产调度。

## 2026-07-19 内部使用口径（后续增量的最高优先级）

用户确认网站后续限制为内部使用，不向未登录用户、公开搜索引擎、QQ 群或其他公开渠道展示
新闻原文和译文；在这一项目策略下，除当前透明请求无法取得内容的站点外，技术可访问来源
均可作为内部候选来源。

本节只覆盖本节生效后的新增行为，并优先于本文较早的 permission `blocked/unknown` 生产
结论。较早章节保留为历史调研和旧实现证据，不再驱动本轮来源准入。新的稳定口径为：

- `technical_access=accepted/blocked`：只描述透明请求、内容类型、host、重定向、响应大小和
  parser 是否可用；`403/429/challenge/login/paywall/robots disallow` 均为 blocked，不绕过。
- `usage_scope=internal_only`：技术 accepted 的来源可以保存正文并翻译，但只能在认证后的
  内部界面使用。
- `public_publish_allowed=false`：所有新五地区来源以及复用来源均禁止公开网页、公开 API、
  sitemap、搜索索引和 QQ 正文分发。
- `production_approved` 继续只是运维启停门，不再表示来源方授权；新来源同步后仍为 false。
- `terms_risk` 继续保留事实性记录，但不再作为本轮内部采集的网络前置阻断条件，也不得显示为
  “来源已授权”。

本口径是项目产品/工程决策，不构成对第三方条款的法律结论。

## 背景与目标

现有新闻链路已承载日本、中国香港、英国、法国和美国。爱尔兰内容当前临时归到英国并附加
`ireland` 标签，加拿大、阿联酋、沙特阿拉伯和澳大利亚内容通常只能归到 `other`，无法形成
独立来源健康、生产窗口、地区筛选、术语审计和 QQ 订阅边界。

本专项新增五个持久地区键：

- `ireland`：爱尔兰
- `canada`：加拿大
- `united_arab_emirates`：阿联酋
- `saudi_arabia`：沙特阿拉伯
- `australia`：澳大利亚

阿联酋与沙特在展示上可以归入“中东”分组，但数据库、归属、来源、配额、审计和 QQ
订阅必须保持两个独立地区，禁止新增含义模糊的持久 `middle_east` 键。爱尔兰不得继续用
英国代替，加拿大不得继续用美国代替。

目标是在不改写现有五地区数据、不扩大赛事历史抓取范围、不默认开启自动发布或 QQ 的前提下，
为五个新地区分别建立至少一个通过真实只读探测的英文新闻来源，并接入现有的
`NewsSource -> adapter -> CrawlJob -> NewsArticle -> 翻译/审核` 链路。生产归属仍为
`off` 时，新文章先保存来源地区，同时生成 source-scoped 只读归属候选；跨地区候选完成人工
确认并锁定前不得发布或推 QQ，不把候选结果冒充已应用主地区。

## 第一批候选来源（历史调研证据，不再执行旧 permission 门禁）

| 地区 | 第一候选与技术入口 | 2026-07-19 首轮真实 probe | 自动化/再利用许可 |
| --- | --- | --- | --- |
| 爱尔兰 | Horse Racing Ireland；列表 `https://www.hri.ie/news-and-media` | HTTP 200、6 条；详情存在 `Saturday, 20 June 2026`，当前解析器缺非 ISO 日期，`deferred` | 官方条款明确禁止未经书面同意的系统化/自动采集，`blocked` |
| 加拿大 | Woodbine；列表 `https://woodbine.com/news/`，文章路径为 `/woodbine-news/` | HTTP 200；当前错误匹配列表根 URL，详情缺时间，`deferred` | 官方条款只允许有限个人/教育用途并限制复制、分发和 deep link，当前生产用途 `blocked` |
| 阿联酋 | Emirates Racing Authority；列表 `https://emiratesracing.com/news` | HTTP 200、1 条；详情 JSON-LD 含 `datePublished`，当前解析器未读取，`deferred` | 官方条款要求内容使用、复制、分发或展示取得书面同意，`blocked` |
| 沙特阿拉伯 | JCSA；页面 `https://jcsa.sa/en/news/`，HTML 片段 `https://jcsa.sa/api/news/en/0/12` | 旧入口是媒体工具页且列表为空；正确片段返回 12 条，补救前 `deferred` | 未找到覆盖自动采集与翻译再利用的一般授权，`unknown` |
| 澳大利亚 | Racing Victoria；页面 `https://www.racingvictoria.com.au/news`，列表发现使用公开 sitemap | 静态新闻页列表为空；浏览器可见动态文章，sitemap 含文章 URL，补救前 `deferred` | 未找到覆盖自动采集与翻译再利用的一般授权，`unknown` |

HTTP 200 只证明入口当前可达，不代表已经获得自动化访问、全文保存、翻译或再发布许可。
任何来源在条款状态不明确、robots 禁止、需登录、需绕过验证码或限制自动访问时，必须保持
`production_approved=false`，不得通过更换 User-Agent、代理或浏览器自动化规避。
robots 对五站当前均未阻断普通新闻路径，但 robots 不是再利用许可。HRI、Woodbine、ERA
即使后续离线 parser fixture 通过，也只能得到 `effective_production_status=production_blocked`；
JCSA、Racing Victoria 在许可保持 `unknown` 时同样不得进入生产。

## 第二批来源调研与复用策略（历史调研证据，不再执行旧 permission 门禁）

本轮不再以“每个地区都新建一个独占 adapter”为目标。爱尔兰、加拿大允许复用英国、美国或
全球来源，但来源身份与文章地区必须分离：

- Sporting Life、Sky Sports Racing、TDN、BloodHorse 等来源报道 Curragh、Irish Oaks、
  Woodbine、King's Plate 等明确地区赛事时，候选地区按文章证据判定，不继承来源默认地区。
- 跨地区复用不得绕过来源自身的许可状态；同一 canonical 来源的条款结论对关键词 adapter、
  地区包装器和普通列表 adapter 一致生效。
- 阿联酋、沙特和澳大利亚继续使用“官方/本地高频/全球补充”三层发现池，但只有
  automation permission 不为 blocked 的来源才允许受控联网详情 probe。

第二批详细矩阵保存在 `source_research.md`。截至 2026-07-19：

- Dubai Racing Club、Gulf News、The National、Just Horse Racing、Breednet、Racing.com、
  Saudi Press Agency 的官方条款均限制自动处理、复制、翻译衍生、存储或商业再利用，记为
  `blocked`，不新增生产 adapter、不重复抓取正文。
- Canadian Thoroughbred 页面和详情技术可达，但未找到覆盖自动采集与翻译再利用的明确授权，
  记为 `unknown`，只允许透明 UA、低预算、零生产写入的技术验证。
- Arab News、Racing and Sports、Racenet、Punters、Racing Queensland 当前透明请求为
  `403`，不得绕过。
- JCSA、Racing Victoria 继续作为沙特、澳大利亚的 permission `unknown` 技术候选；淡季无
  新稿是正常季节性事实，不用放宽 freshness 或抓取限制制造结果。
- permission SHALL 由单一 canonical registry 在任何列表/详情请求前解析；adapter 自报字段、
  wrapper 名称或地区不得把 canonical `blocked` 降为 `unknown`。
- blocked 来源的 probe/crawl SHALL 返回明确 `permission_blocked_preflight` 且网络请求数为
  `0`；unknown 来源只有实现可注入请求预算协议时才允许显式 research probe。

## 范围

### 包含

- 新增五个地区 choice、中文标签和稳定排序。
- 为五个候选来源增加独立 `SourceSite`、`NewsSource` 定义和英文适配器。
- 列表与详情解析：标题、正文、可信发布时间、作者、原文 URL、来源语言、来源地区和解析证据。
- 新地区只读探测、fixture 测试、来源健康、失败/backoff 和生产审计。
- 爱尔兰/英国、加拿大/美国、阿联酋/沙特及澳大利亚跨地区报道的主地区/关联地区判定。
- 新闻前台和运营后台的新地区筛选；“中东”只作为阿联酋、沙特的展示分组。
- QQ 群可单独订阅五个新地区，但既有群的空配置继续只代表日本。
- 新来源默认停用且未获生产批准；抓取、自动发布、关联地区查询和 QQ 均需后续逐层灰度。
- 审计所有依赖 `RacingRegion.values/choices` 的非新闻代码，防止历史赛事、准实时赛事、
  马匹补全或赛事日历因 choice 扩展而自动扩大范围。

### 不包含

- 新地区赛事日历、出马表、赛果、历届冠军或马匹资料抓取。
- 将旧 `other` 或 `ireland` 标签文章自动批量改写为新地区。
- 自动启用新来源、自动发布、QQ 推送或生产部署。
- 抓取付费墙、登录后内容、图片/视频、赔率、tips 或受限制的结构化赛事数据。
- 把阿联酋与沙特合并为一个持久地区。
- 在本专项中开启现有多地区归属的 `enforce`、关联地区查询或历史回填。
- Google News RSS discovery collector；本轮只记录研究方法，不保存聚合 metadata、正文或
  `NewsArticle`，后续如实现必须另补 metadata-only 和原站解析门禁。

## Requirements

### Requirement 1：五个新地区必须具有独立持久身份

- `RacingRegion` SHALL 新增五个稳定值，已有值和数据库内容 SHALL 保持不变。
- 阿联酋和沙特 SHALL 分别计数、筛选、配置、审计和订阅；“中东”只可用于 UI 分组。
- `other` SHALL 继续表示尚未建模的地区，不得继续代表本次五个新地区的新文章。
- 任何共享枚举消费者 SHALL 使用显式能力列表，禁止把 `RacingRegion.values` 等同于
  “历史赛事支持地区”“准实时支持地区”或“马匹补全支持地区”。

### Requirement 2：每个地区必须至少有一个可独立停用的来源

- 每个候选来源 SHALL 使用独立 `SourceSite` 和 adapter key。
- 来源同步后的初始状态 MUST 为 `enabled=false`、`production_approved=false`。
- probe SHALL 使用当前三轴稳定状态：
  - `technical_access=accepted/blocked`
  - `usage_scope=internal_only`
  - `public_publish_allowed=false`
- 只有技术 accepted 才计入“内部来源齐备”；terms 风险单独记录，不得显示为已授权。
- probe 证据 SHALL 绑定 source key、入口/最终 URL、adapter/parser version、审核时间和
  artifact SHA-256，且 probe 不得修改 `NewsSource.production_approved`。
- 每个地区至少一个来源达到 `eligible` 后，才能把该地区标记为“抓取能力可灰度”。
- 某个地区来源 no-go 不得阻断其他地区完成，但项目级“本次五地区来源齐备”只有在五个地区
  都至少一个 `effective_production_status=eligible` 来源时才成立。单独
  `technical_status=accepted` 只能表示解析能力，不表示可灰度来源。

### Requirement 3：可信发布时间和内容边界必须 fail closed

- 新适配器 MUST NOT 用抓取时间代替缺失或不可解析的原文发布时间。
- 发布时间必须记录原始文本、解析时区、解析器版本和 verified 状态；Dublin、Toronto、
  Dubai、Riyadh、Melbourne 时区及夏令时必须按来源所在地处理。
- 缺少可信发布时间、标题或正文的单篇文章 SHALL 被跳过并记录原因，同轮其他文章继续。
- 若整轮列表为空或全部详情失败，`CrawlJob` SHALL 失败或给出明确 deferred 原因，不得写入空壳文章。
- 对本次新来源，HTTP 200 但解析列表为空 SHALL 记为 `empty_listing` 失败并进入来源健康/
  backoff；“全部是重复文章”仍 SHALL 记为成功无新增，两者不得混淆。
- 正文清洗 SHALL 复用现有国际新闻内容边界，排除导航、页脚、推荐卡、投注提示、登录提示
  和版权声明，不抓图片、视频或嵌入式投注组件。
- 新来源请求 SHALL 只允许 HTTPS 和 adapter 声明的初始/最终 host，限制重定向次数、
  默认只接受 `text/html`/`application/xhtml+xml`；Racing Victoria 仅其声明的 sitemap
  入口可额外接受 `text/xml`/`application/xml`。所有响应最大 2 MiB，并限制 connect/read timeout，
  并拒绝 off-host redirect、二进制、超限、登录页和验证码页。不得使用来源专属代理轮换、
  浏览器伪装或 User-Agent 轮换规避限制。
- 新来源请求 MUST 使用可识别的固定项目 User-Agent；不得沿用浏览器品牌字符串冒充交互式浏览器。
- 非 200 响应 SHALL fail closed，并在 probe/crawl 中保留最终 URL 和精确 HTTP 状态；
  至少 `403` 与 `429` 不得被折叠成无状态的通用解析错误。
- HRI 可见英文长日期、Woodbine/ERA 的 JSON-LD 或
  `article:published_time`、JCSA 的英文序数日期 SHALL 使用来源限定的格式白名单解析；
  禁止引入任意自然语言日期猜测或 crawl time 兜底。
- Racing Victoria 详情 SHALL 从服务端返回的 `__NEXT_DATA__` 中限定读取 route
  `Title/ArticleDate` 和 `headless-main` 下的 `RichText` 正文；不得把 `headless-footer`
  版权文本或 `DCAArticleList` 推荐内容作为正文。
- 当 evidence `precision=date`、原文只有发表日期时，候选判定 SHALL 把抓取时间转换到
  evidence 声明的来源时区，以“来源当地发表日期”和“来源当地抓取日期”的绝对日差计算：
  `date_difference_days <= 1` 可进入候选池，`> 1` 记为历史新闻并跳过候选入库。
- date-only 文章可以为便于排序把 `published_at` 规范化为来源当地 12:00，但 freshness
  SHALL 只比较当地日期，不得把 12:00 当作精确发表时刻，也不得套用 6 小时精确时间窗口。
- 非 date-only 的精确时间继续遵循既有来源/窗口规则；本增量不得借日期规则扩大其 freshness。
- evidence 时区缺失或无效时 SHALL fail closed 并记录 `invalid_published_timezone`，不得
  回退到服务器、Django 默认或抓取者本地时区。
- probe/crawl 摘要 SHALL 区分 `candidate_date_within_one_day`、
  `historical_date_outside_one_day`、`missing_published_at` 与精确时间路径；历史新闻不写
  `NewsArticle`，同轮其他详情继续。
- 只有 `published_at`/抓取时间均为 aware、evidence 与 draft 的 verified 标志均为真、
  precision 为 `date/minute/second` 时才是可判定时间；verified 精确时间走既有路径，
  precision 缺失/未知、verified false、naive datetime 或时间为空均为 `unresolved`。
- 上述严格门禁应用于本专项新五地区候选；复用来源缺可信时间时不得用 listing crawl time
  伪装为 Ireland/Canada 新稿，不改变未归属新五地区的旧国际文章兼容行为。
- candidate scope SHALL 在 upsert 前用正式归属模块的共享纯函数预判；处理顺序为
  `normalize -> preview target -> target freshness -> upsert -> reuse preview candidate`。
  历史/未决目标稿必须在 upsert 前停止，普通 UK/US 稿保持旧行为，前后不得维护两套关键词。
- 同一 probe/crawl SHALL 固定一个 aware 抓取时间。候选 freshness 的判定、当地日期和日差
  SHALL 随 draft/article snapshot 持久化；历史/未决计数 SHALL 出现在 CrawlJob/窗口摘要。

### Requirement 4：爱尔兰/英国和加拿大/美国必须可区分

- 明确爱尔兰赛事/赛场/机构信号的归属候选 SHALL 为 `ireland`，不得只附 `ireland`
  标签后仍把英国当作候选主地区。
- 明确加拿大赛事/赛场/机构信号的归属候选 SHALL 为 `canada`，不得因英文或北美来源
  默认把美国当作候选主地区。
- Sporting Life 等英国来源报道爱尔兰本地赛事时，候选主地区 SHALL 为爱尔兰。
- Woodbine 等加拿大来源报道美国赛事且标题存在强赛事证据时，候选主地区可以是美国，但
  加拿大 SHALL 作为候选关联地区；反向场景同理。
- 来源地区只作回退或关联证据，不得压过标题中的强赛事/赛场证据。
- 全局归属 mode 为 `off` 时，上述结果只保存到 `review_candidate`，`NewsArticle.racing_region`
  仍为来源地区；文章强制 `manual_review_required`，完成人工地区确认并设置
  `attribution_locked=true` 前不得公开或推 QQ。
- 全局 `enforce` 不由本 change 开启；未来自动应用新地区归属必须先建立新规则版本的
  Gold/Shadow 资格。
- 全局 mode `off` 时，复用来源 SHALL 使用 content-scoped candidate 路径：只有标题/导语
  强事件证据推断为 Ireland/Canada、且 canonical 来源在独立研究 allowlist 中的文章才保存
  `review_candidate` 并增加人工地区门禁；同一来源普通 UK/US 稿保持现有行为。
- content-scoped candidate 总开关和 canonical source allowlist 默认关闭/空。调度只抓取
  canonical 来源一次，不创建 Ireland/Canada wrapper，不因同稿地区命中重复 upsert。

### Requirement 5：阿联酋、沙特和澳大利亚必须进入正式归属词表

- UAE、Dubai、Meydan、Emirates Racing Authority 等强信号 SHALL 指向阿联酋。
- Saudi Arabia、Saudi Cup、Riyadh、King Abdulaziz Racecourse、JCSA 等强信号 SHALL
  指向沙特阿拉伯。
- Australia、Australian、Racing Victoria、Flemington、Randwick、Rosehill、
  Caulfield、Melbourne Cup 等强信号 SHALL 指向澳大利亚。
- 上述词不再作为 `out_of_scope_title_region` 统一压到 `other`。
- 同一标题出现多个互斥强赛事中心时 SHALL 进入 `needs_review`，不得按关键词顺序静默选一个。

### Requirement 6：跨地区文章必须保持单一主地区和有界关联地区

- 主地区继续决定发布窗口与主配额，关联地区只用于可见性、订阅和审计。
- 明确外国赛事报道中，赛事地通常为主地区；来源/核心对象所在地区可以成为关联地区。
- 关联地区去重、固定排序且最多 3 个；超过上限或存在冲突时进入 `needs_review`。
- 归属规则版本 SHALL 前进，现有 Gold/Shadow 资格不得自动覆盖新规则和新地区。
- 新地区规则只对新抓取文章执行；旧 `other`/`ireland` 文章仅先生成只读候选清单，
  后续需独立审核和授权才可回填。
- 新来源使用独立、默认关闭的 source-scoped 候选开关和 source allowlist；该开关只写
  `review_candidate` 与人工审核门禁，不写主/关联地区。未在 allowlist 的旧来源在全局
  mode `off` 下保持现状。

### Requirement 7：新地区必须接入现有灰度和审计边界

- 新来源只有同时满足 `enabled=true`、`production_approved=true`、地区/来源 allowlist、
  未暂停、未 backoff 和到期时才可被生产窗口选择。
- 非日本新地区默认人工审核；自动发布 allowlist 为空时不得自动发布。
- 新来源文章即使通过翻译与其他门禁，只要地区候选尚未人工确认并锁定，就必须被
  `region_review_required` 或等价硬门禁阻止进入内部已发布状态。
- 内部模式下 QQ 对所有地区一律阻断；既有 `allowed_regions` 仅保留兼容数据，不产生发送。
- 运营后台 SHALL 能按五个新地区查看来源状态、新增、重复、解析失败、缺失时间、翻译状态、
  门禁原因、内部已发布数和外部分发阻断状态。
- 认证后的新闻首页 SHALL 使用新闻专属地区 resolver 提供可到达的新地区筛选；阿联酋和沙特
  可在“中东”视觉分组下展示，但查询参数和值必须独立。马匹索引和赛事日历 SHALL 使用各自
  显式地区集合，不显示也不接受本次尚未具备对应数据能力的新地区。

### Requirement 8：扩展新闻地区不得扩大赛事和马匹任务范围

- 历史赛事批次、准实时赛事 initializer/selector、赛事日历 tab、距离单位和马匹补全 SHALL
  继续只处理其各自已明确支持的地区。
- 新增 choice 后，现有历史赛事应到分母、准实时 allowlist、马匹补全队列和赛事日历标签
  SHALL 与变更前一致。
- 如未来要为五个新地区接入结构化赛事或马匹数据，必须另起专项并新增对应来源与验收。

### Requirement 9：网站和新闻内容必须真正内部化

- 新增 `SITE_INTERNAL_ONLY_ENABLED`，默认值必须为 `true`；关闭必须是显式运维动作。
- 开启时，除登录、登出、静态资源、`robots.txt` 和 `/healthz/` 外，全部网页与 API 均要求
  已认证会话。HTML 请求重定向到登录页并保留安全的 `next`；API 返回 `401` JSON，不返回
  新闻、赛事、马匹或翻译数据。
- `robots.txt` 在内部模式下必须返回 `Disallow: /`；sitemap 不得向未登录请求返回内容。
- 内部模式不得改变 `/healthz/` 的无认证可用性，不得造成登录页重定向循环，也不得阻断
  Django admin 登录。
- `/media/` 属于内部边界：Nginx 不得继续直接 `alias` 公开文件；local media 必须经认证
  view/X-Accel-Redirect 读取。OSS 只有在私有 bucket + 短期签名 URL 模式通过预检时可用，
  否则内部模式启动/部署必须 fail closed。
- `DEBUG=false` 时必须同时开启 session/CSRF secure cookies。传输层只能选择 direct
  `SECURE_SSL_REDIRECT=true`，或显式
  `SITE_INTERNAL_ONLY_TRUSTED_TLS_TERMINATION=true` 并提供合法
  `SECURE_PROXY_SSL_HEADER` HTTPS 合同；缺任一项启动 fail closed。当前 HTTP-only Nginx
  不能作为本任务生产验收入口。
- 新抓取来源不下载或复制图片、视频、赔率和付费内容；本批 adapter 的 `images` 必须为空。

### Requirement 10：公开发布和外部分发必须有独立硬门

- 内部模式允许沿用 `WorkflowStatus.PUBLISHED` 表示“内部已发布/可阅读”，但相应 URL 仍须登录。
- QQ 自动推送、单篇 QQ 推送、公开 URL 可用性检查和任何新闻正文外发在内部模式下一律返回
  `internal_only_distribution_blocked`，且不得创建或发送新的 delivery。
- 旧手动 `PushLog`/OneBot 路径也必须在创建 PushLog 前阻断。所有带文章上下文的邮件、QQ
  warning、翻译恢复通知和 ops payload 必须通过同一 blocker/sanitizer。
- 自动发布与人工发布不得绕过认证门；公开 sitemap、匿名文章详情和匿名列表均不得因已有
  `published_to_web_at` 而泄露内容。
- `usage_scope=internal_only` / `public_publish_allowed=false` 是独立来源级硬门；即使
  `SITE_INTERNAL_ONLY_ENABLED=false`，公开 queryset、详情和 QQ 也必须复用文章级 blocker
  排除相应稿件。
- 运维通知只允许字段白名单：任务名、稳定错误分类、计数、时间和内部对象 ID；不得包含原文
  标题、正文、译文、摘要或来源 URL。文章级通知只使用安全 `article_id`；无法证明 payload
  安全时不发送。

### Requirement 11：技术准入与使用范围必须解耦

- canonical 来源 registry 必须记录 `technical_access`、`usage_scope`、
  `public_publish_allowed`、`terms_risk`、允许 host 和证据日期。
- 对 registry 管理的来源，只有 `technical_access=accepted` 才可进入内部 crawl；
  `technical_access=blocked` 必须在任何列表或详情请求前停止。
- adapter/wrapper 不得改变 canonical 技术结论；host 超出 allowlist、透明请求发生
  `403/429/challenge/login/paywall/robots disallow` 时 fail closed。
- 技术 accepted 不自动设置 `NewsSource.enabled` 或 `production_approved`；来源必须经过
  独立启用、allowlist、到期和 backoff 门禁。
- registry、probe 和后台不得使用 “permission approved” 表述对外暗示授权；历史字段如为
  兼容保留，展示层必须同时标明 `usage_scope=internal_only` 和
  `public_publish_allowed=false`。

### Requirement 12：第三批直接来源池

在既有 HRI、Woodbine、ERA、JCSA、Racing Victoria 五源之外，新增以下首批多来源：

| 地区 | 新增来源 |
| --- | --- |
| 爱尔兰 | RTÉ Racing RSS、IrishRacing HTML |
| 加拿大 | Canadian Thoroughbred HTML、Assiniboia Downs RSS |
| 阿联酋 | Dubai Racing Club RSS/WP、The National Horse Racing HTML |
| 沙特阿拉伯 | Saudi Press Agency HTML、Arab News Horse Racing HTML |
| 澳大利亚 | Just Horse Racing RSS、The Straight RSS、Racing NSW RSS、Tasracing RSS |

- 每个来源必须有独立 `SourceSite`、adapter key、host allowlist、时区、parser version、
  技术状态、停用开关和 crawl interval。
- RSS 必须解析 GUID/link、标题和精确时间；详情仍通过有界 HTTPS helper 抓取并执行正文清洗。
- IrishRacing、Canadian Thoroughbred 等 date-only 详情继续执行当地日期日差 `0/1` 候选、
  `>1` 历史规则。
- Just Horse Racing 排除 tips/odds；Tasracing 仅保留 thoroughbred，排除 harness 和
  greyhound；SPA 排除 camel、show jumping 和非赛马稿。
- Google News RSS 不属于本批实现；未来只能作为 metadata-only discovery，且只有解析到
  原站 URL、原站技术 accepted 并通过 canonical 来源门禁后才可进入详情抓取。

### Requirement 13：翻译处理范围必须可审计

- 内部来源文章可以进入现有翻译链路；`TranslationRun` 必须记录 provider/model，不得把
  dummy 输出计作中文翻译成功。
- 是否允许把正文、译文或术语发送给外部 AI provider 必须由共享
  `NEWS_EXTERNAL_AI_PROCESSING_ENABLED` 配置控制，默认 false；门禁覆盖 translation、
  rewrite 及其 Celery 直接入口。false 时只允许本地 provider 或明确的 dummy 测试，不丢弃
  已抓取候选。
- 开启外部 provider 不改变 `public_publish_allowed=false`，也不得自动启用 QQ。
- 本轮真实外部来源验证优先完成采集与 parser；若没有可用翻译 provider，必须报告
  “抓取成功、真实翻译未验证”，不得用合成文本替代结果口径。

## 验收标准

1. 五个地区键可在模型、后台、新闻筛选、来源审计和 QQ 配置中独立使用。
2. 既有五个和第三批十二个 adapter 都有离线 fixture 覆盖；真实只读探测按当前技术准入输出
   列表、详情、时间和解析质量。
3. 每个地区至少两个独立入口中至少一个 `technical_access=accepted`，且所有可用入口均明确
   `usage_scope=internal_only/public_publish_allowed=false`，才可宣称内部抓取能力齐备。
4. 爱尔兰/英国、加拿大/美国、UAE/沙特、澳大利亚跨地区推断用例全部通过且不回退到
   `other`；在实际计划 settings（全局 mode off）下的 adapter→upsert 端到端测试证明只写
   `review_candidate`、保持来源主地区并阻止公开/QQ，人工确认后才应用并锁定最终地区。
5. 缺发布时间、空正文、403/429、单篇失败、全轮失败和重复文章均有可审计结果。
6. 新来源同步后默认停用且未生产批准；自动发布、QQ 和关联地区查询不因迁移自动打开。
7. 历史赛事、准实时赛事、赛事日历和马匹补全的地区集合回归测试证明范围未扩大。
8. Django check、迁移漂移、目标测试、受影响回归、Compose 配置和 `git diff --check` 通过。
9. date-only fixture 覆盖日差 `0/1/2`、跨 UTC 日期边界、夏令时和无效时区；`0/1` 进入候选，
   `2` 为历史，且不会改变精确时间文章的既有行为。
10. 复用来源样本证明 `Irish Oaks` 不再回退到英国、Woodbine/Ontario 强信号不回退到美国；
    technical blocked 的 canonical 来源不因地区包装器而重新获得联网资格。
11. canonical technical-access resolver 在任何 adapter 网络调用前生效：blocked 来源、
    wrapper、显式 probe、隔离 runner 与 direct crawl 均为零请求；direct task 不得通过 flag
    或调用参数绕过。未登记 legacy 来源不得新增技术前置条件，现有自动选择集合保持不变。
12. technical accepted 来源只有在 `enabled=true + production_approved=true + allowlist`
    等运维门禁满足时才能创建内部候选；公开读取与外部分发始终由内部模式硬门阻断。
13. registry 未登记的变更前 legacy 国际来源完全保持变更前的选择/direct-crawl 条件，并输出
    `legacy_permission_unregistered`；该标记不得被显示为许可 approved，也不得用于本轮新五
    地区 content-scoped 候选。本增量必须用变更前 enabled + production-approved 来源快照做
    集合相等回归，不能只证明“仍有若干来源”。
14. 技术 probe 的 listing `1`、detail `2` 是实际 HTTP transport GET 预算，不是逻辑
    helper 调用数；重定向、失败响应和重试尝试均须在每个 `session.get()` 前消费，耗尽后零
    额外网络调用。
15. content-scoped 归属由入库前的单一纯函数生成不可变 preview result；同一 result 决定是否
    应用严格 freshness 并传给 upsert/正式 attribution。Ireland/Canada 缺可信时间稿在 upsert
    前停止，同源普通 UK/US 稿不进入本增量 freshness。
16. 内部模式匿名访问矩阵、API `401`、登录回跳、login/admin/healthz 例外、robots 和 sitemap
    全部通过自动化测试；QQ 和公开分发硬门在任何来源状态下均无外发副作用。
17. 上表 12 个新增来源均有离线 fixture；每地区至少两个技术独立的直接获取入口可用。仅当前
    真实透明请求 `403/429/challenge/login/paywall/robots disallow` 的来源标记 blocked。
18. 来源 registry 的技术状态、内部 scope 和公开禁止三轴可审计；新来源仍默认
    `enabled=false/production_approved=false`，不会因 migration 或同步自动联网。
19. 外部 translation/rewrite 处理默认关闭；本地/dummy 与真实外部 provider 的运行结果分别
    报告。

## 失败边界

- 任一来源出现 `403/429/challenge/login/paywall/robots disallow`、host 越界、响应超限或
  parser 无法确认正文边界：标记 technical blocked，保留证据，不绕过。
- 任一地区没有 technical accepted 来源：该地区不得启用内部常态抓取，项目状态明确为部分完成。
- 新 choice 使非新闻任务范围扩张：阻断实现与发布，先改为显式能力列表并补回归。
- 真实探测只可在独立请求预算内执行，不写 `NewsArticle`、不翻译、不发布、不推 QQ。
- 若隔离实抓没有 freshness 合格候选，翻译链路 SHALL 报告“无候选可运行”，不得改抓历史稿
  或绕过 technical access。Dummy provider 的成功状态只证明任务机械链路，不是中文翻译成功。
- 全局归属 mode `off` 时不得声称跨地区候选已经写成主地区；候选未审核文章必须 fail closed。
- 本专项不包含生产发布；完成代码审核后仍需用户针对冻结内容另行授权。
- 本轮新口径下，较早的 terms `blocked/unknown` 结论不再阻止技术 accepted 来源的内部采集；
  但旧结论保留为 `terms_risk`，不得被改写成来源已授权。
- `SITE_INTERNAL_ONLY_ENABLED=false`、`NEWS_EXTERNAL_AI_PROCESSING_ENABLED=true`、QQ
  重新开启或任何匿名内容恢复都属于
  独立高风险发布动作，不包含在“接入更多来源”的隐含范围内。
