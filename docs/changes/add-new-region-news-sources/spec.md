# 新地区新闻抓取规格

## 文档状态

- 专项：爱尔兰、加拿大、阿联酋、沙特阿拉伯、澳大利亚新闻抓取
- 基线：`origin/main@566a9b1012aac7fe52ad7aec793ab0ff4b9eae18`
- 分支：`codex/add-new-region-news-sources-integrated`
- 阶段：补救方案两轮复审已通过；真实结构、权限与 HTTP 诊断已完成 RED/GREEN，待最新指纹代码复审
- 生产状态：代码未提交、migration 未应用、未部署、未启用任何新来源
- 在线入口核对日期：2026-07-19

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

## 第一批候选来源

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
- probe SHALL 使用三段稳定状态：
  - `technical_status=accepted/deferred/blocked`
  - `automation_permission_status=approved/unknown/blocked/expired`
  - `effective_production_status=eligible/production_blocked`
- 只有技术通过且自动化许可为 approved 时，`effective_production_status` 才可为 `eligible`，
  并计入“五地区来源齐备”；条款未知时即使解析成功也必须是 `production_blocked`。
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
  `region_review_required` 或等价硬门禁阻止发布和 QQ。
- QQ 仅在群 `allowed_regions` 显式包含对应地区时发送；空/非法配置继续只允许日本。
- 运营后台 SHALL 能按五个新地区查看来源状态、新增、重复、解析失败、缺失时间、翻译状态、
  门禁原因、公开数和 QQ 状态。
- 公共新闻首页 SHALL 使用新闻专属地区 resolver 提供可到达的新地区筛选；阿联酋和沙特
  可在“中东”视觉分组下展示，但查询参数和值必须独立。马匹索引和赛事日历 SHALL 使用各自
  显式地区集合，不显示也不接受本次尚未具备对应数据能力的新地区。

### Requirement 8：扩展新闻地区不得扩大赛事和马匹任务范围

- 历史赛事批次、准实时赛事 initializer/selector、赛事日历 tab、距离单位和马匹补全 SHALL
  继续只处理其各自已明确支持的地区。
- 新增 choice 后，现有历史赛事应到分母、准实时 allowlist、马匹补全队列和赛事日历标签
  SHALL 与变更前一致。
- 如未来要为五个新地区接入结构化赛事或马匹数据，必须另起专项并新增对应来源与验收。

## 验收标准

1. 五个地区键可在模型、后台、新闻筛选、来源审计和 QQ 配置中独立使用。
2. 五个候选 adapter 都有离线 fixture 覆盖，且至少各一次真实只读探测输出列表、详情、时间和解析质量。
3. 每个地区至少一个来源为 `technical_status=accepted`、许可 `approved` 且 effective
   `eligible` 才能宣称五地区抓取能力齐备；条款未知时仍为 `production_blocked`。
4. 爱尔兰/英国、加拿大/美国、UAE/沙特、澳大利亚跨地区推断用例全部通过且不回退到
   `other`；在实际计划 settings（全局 mode off）下的 adapter→upsert 端到端测试证明只写
   `review_candidate`、保持来源主地区并阻止公开/QQ，人工确认后才应用并锁定最终地区。
5. 缺发布时间、空正文、403/429、单篇失败、全轮失败和重复文章均有可审计结果。
6. 新来源同步后默认停用且未生产批准；自动发布、QQ 和关联地区查询不因迁移自动打开。
7. 历史赛事、准实时赛事、赛事日历和马匹补全的地区集合回归测试证明范围未扩大。
8. Django check、迁移漂移、目标测试、受影响回归、Compose 配置和 `git diff --check` 通过。

## 失败边界

- 任一来源条款/robots 不允许自动化：该来源 no-go，保留证据，不绕过。
- 任一地区没有 `eligible` 来源：该地区不进入生产灰度，项目状态明确为部分完成；
  技术 accepted 不能替代许可 approved。
- HRI、Woodbine、ERA 在当前 `blocked` 结论下只可使用已保存的最小证据做离线 fixture；
  取得新的书面许可前不得再次联网 probe。
- JCSA、Racing Victoria 在 permission `unknown` 时只允许本专项显式命令、透明 User-Agent、
  每源列表 1 次/详情最多 2 次的只读技术复测；如 robots/条款出现禁止信号立即停止。
- 新 choice 使非新闻任务范围扩张：阻断实现与发布，先改为显式能力列表并补回归。
- 真实探测只可在独立请求预算内执行，不写 `NewsArticle`、不翻译、不发布、不推 QQ。
- 全局归属 mode `off` 时不得声称跨地区候选已经写成主地区；候选未审核文章必须 fail closed。
- 本专项不包含生产发布；完成代码审核后仍需用户针对冻结内容另行授权。
