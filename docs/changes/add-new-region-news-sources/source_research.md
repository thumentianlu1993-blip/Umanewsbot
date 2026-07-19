# 新五地区第二批新闻来源调研

## 最新集成结论

- 当前验收入口为
  `/Users/mentianlu/Code/umanews/.worktrees/add-new-region-news-sources-release-candidate`，
  当前 `HEAD=origin/main=a122ff6dde16ab4b53f34e446b0f959751ad7a77`，
  `origin/main..HEAD=0`。
- 第三轮已用迁移后的仓库外 `/tmp` SQLite、透明 bounded HTTP、每源 listing `1`/detail
  最多 `2` 完成受控 live probe；首次空库 `no such table` 仅为环境错误，迁移后重跑结果才
  进入下表。
- 24-source technical registry 为 `16 accepted / 8 blocked`；第三批 12 源为
  `8 accepted / 4 blocked`。所有来源均为
  `usage_scope=internal_only / public_publish_allowed=false`，所有第三批 source definition
  继续 `enabled=false / production_approved=false`；accepted 不等于 eligible、启用或生产批准。
- 可信 date-only 稿只按来源当地发表日与抓取日差判断：`0/1` 天进入候选，`>1` 天归历史；
  无可信时间、evidence/precision 不完整或时区无效归 `unresolved`，不入库。本轮所有样本
  都有精确时刻，没有用 date-only 兜底提高六小时计数。
- 来源 technical accepted 也不改变内容边界：`usage_scope=internal_only` /
  `public_publish_allowed=false` 会独立阻断公开 queryset、详情和 QQ，即使全局站点登录墙关闭
  也不能提升稿件。
- 首次代码审核七项 finding 已修复，但 reviewer 完整性因 main 漂移保持 `BLOCKED`；当前
  已重新集成最新 main，仍须复审最终精确版本。完成复审前不得把任一 adapter 写为 release
  approved。

### 24-source live technical registry

| Technical | 来源 key |
| --- | --- |
| accepted `16` | `rte_racing`、`irishracing_news`、`dubai_racing_club`、`jcsa_news`、`spa_horse_racing`、`racing_victoria_news`、`just_horse_racing`、`the_straight`、`racing_nsw_news`、`tasracing_news`、`tdn`、`bloodhorse`、`horse_racing_nation`、`sky_sports_racing`、`sporting_life`、`bha` |
| blocked `8` | `hri_news`、`woodbine_news`、`canadian_thoroughbred`、`assiniboia_downs_news`、`emirates_racing_authority`、`the_national_racing`、`arab_news_racing`、`paulick_report` |

- 第三批的四个 blocked 精确为 Canadian Thoroughbred、Assiniboia Downs、The National、
  Arab News；其余八源 accepted。
- IrishRacing、SPA、Racing NSW、Tasracing 根据 live 结构完成 TDD 修复后复探 accepted。
  Racing NSW 额外排除 tips/preview，且 generic `Latest News` 不能覆盖 RSS 标题。
- HRI、Woodbine、ERA listing HTTP `200`，但详情均因 `missing_published_at` 端到端
  fail closed。TDN 详情正文成功后 technical accepted，但该次样本时间 unverified，不能进入
  freshness 候选。JCSA、Racing Victoria 的 live 结果为 accepted。
- TDN、BloodHorse、Horse Racing Nation、Sky Sports Racing、Sporting Life、BHA 进入
  internal-only 综合技术池。离线 attribution 测试确认 Curragh/Irish Oaks -> Ireland、
  Woodbine/Canadian -> Canada，无强关键词保留原 US/UK region。Sporting Life 当前样本因
  unverified time 只记 candidate deferred。

### 最新严格六小时候选

probe 时点约 `2026-07-19T17:41Z`，窗口约 `11:41Z..17:41Z`：

| 地区 | 候选数 | 可信候选 |
| --- | ---: | --- |
| Ireland | 2 | RTÉ `Power Blue back to winning ways at the Curragh`，`15:09:15Z`，verified；IrishRacing `Tokyo Tower shows resolution to land Curragh finale`，`16:51:00Z`，verified |
| Canada | 0 | 无 |
| UAE | 0 | 无 |
| Saudi Arabia | 0 | 无 |
| Australia | 0 | 无 |

TDN `17:28:05Z` 因 unverified 不计；Just Horse Racing `10:09:13Z` 已超窗。Dubai Racing
Club `07-09`、JCSA `03-22`、SPA `01-07`、Racing Victoria `07-15`、The Straight
`07-17`、Racing NSW `07:32`、Tasracing `07-03` 均不计。

### 翻译编排边界

同一迁移临时库使用真实 RTÉ 正文 `6616` 字符和
`TRANSLATION_PROVIDER=dummy`；外部 AI 默认关闭。
`translate_article_task` 返回 `translated=true`，文章 status 为 `translated`，
`TranslationRun=success`，标题带 `[未配置真实翻译模型]`。本机 SiliconFlow/OpenAI key
均 absent，因此只证明任务与持久化编排通过，不能写成真实中文远程翻译完成。

## 口径

- 核对日期：2026-07-19
- `technical` 只表示透明请求和解析可行性，不代表允许保存、翻译或再发布。
- `permission=blocked`：官方条款明确限制自动处理、复制、存储、修改、翻译衍生或商业使用。
- `permission=unknown`：未找到覆盖本项目用途的明确授权；只能保持生产关闭并做有界技术验证。
- robots 只用于抓取路径诊断，不作为内容再利用许可。
- 当前没有任何第二批来源因此调研被提升为 `eligible`。

## 爱尔兰

| 来源 | 技术/新鲜度证据 | Permission | 结论 |
| --- | --- | --- | --- |
| Sporting Life Racing | HTTP 200；最新 3 条中有 Curragh 稿；详情正文可解析但可信时间缺失 | unknown | 可复用发现；不能计入六小时精确候选 |
| Sky Sports Racing | 列表曾返回多条 Irish Oaks/Irish Derby；透明 UA 当前可能进入 client challenge | unknown | 技术不稳定；不可绕过 challenge |
| TDN | WordPress API 有精确 `date_gmt`，Curragh 检索密度高 | blocked | 用户协议限制复制/发布/再分发；只保留元数据证据 |
| BloodHorse | 最新列表可命中 Irish Oaks/Curragh；正文可解析，现 adapter 时间证据不足 | unknown | 次级复用候选 |
| IrishRacing | news sitemap 有标题和时间，正文技术优秀 | blocked | 条款限制商业利用、复制和传播 |
| Racing TV | 当前爱尔兰新闻密度高，页面主要 JS | unknown | 需官方 Feed/API 与许可 |
| At The Races | 普通浏览曾可达；透明项目 UA 当前返回 Client Challenge | unknown | 当前 technical blocked，不绕过 |
| Racing Post Ireland | 专区覆盖高 | blocked | 透明请求 406/付费与许可门槛 |
| IHRB | 官方监管公告可达、频率低 | unknown | 适合事实补充，不是高频主源 |
| HRI | 第一批 adapter 已实现 | blocked | 不再联网 |

复用验收重点：补 `Irish Oaks` 强信号；Curragh/Irish Derby 已可正确归 Ireland。

## 加拿大

| 来源 | 技术/新鲜度证据 | Permission | 结论 |
| --- | --- | --- | --- |
| TDN | Woodbine 关键词 API 可返回精确时间，但会混入只在正文提及 Woodbine 的美国稿 | blocked | 只保留元数据；必须二次归属过滤 |
| BloodHorse | 最新列表可出现 Woodbine 官方/赛事报道 | unknown | 次级复用候选 |
| Horse Racing Nation | 时间解析可靠，当前最新样本加拿大密度低 | unknown | 低频补充 |
| Canadian Thoroughbred | `/news/` HTTP 200；文章路径 `/horse-news/`；详情 `<time datetime=YYYY-MM-DD>`、正文可解析 | unknown | 最强本地技术候选；date-only 适用 1 天规则 |
| Ontario Racing | 原 news URL 重定向到赛果/standings | unknown | 需重新定位真实新闻入口 |
| America's Best Racing | HTTP 200，偶有 Woodbine | unknown | 全球次级补充 |
| Woodbine | 第一批 adapter 已实现 | blocked | 不再联网 |

2026-07-19 抽样 Canadian Thoroughbred 最新详情日期为 `2026-07-17`；按新规则与来源当地
抓取日期日差为 2 时应标记历史，不因首次抓取而入候选。

## 阿联酋

| 来源 | 技术/新鲜度证据 | Permission | 结论 |
| --- | --- | --- | --- |
| Emirates Racing Authority | 第一批 adapter 可解析 JSON-LD 时间 | blocked | 不再联网 |
| Dubai Racing Club | news page 与 WP API 可达，精确 `date_gmt`；存在 `Copy` 重复稿 | blocked | 条款要求书面同意；不新增联网 adapter |
| Gulf News Horse Racing | 专区密度高，页面可达但很大 | blocked | 条款限制复制、衍生和非个人用途 |
| The National Horse Racing | 专区可达、Meydan覆盖高 | blocked | 条款限制复制、存储、修改和分发 |
| Godolphin News | 全球马房新闻可达 | unknown | 仅强 Dubai/Meydan 证据时作为 discovery |
| NMO/WAM | 官方稿有 UAE President's Cup 等赛马内容，但无稳定赛马列表 | unknown | 低频官方 discovery，待 API/许可 |
| Racing Post UAE | 专区覆盖高 | blocked | 透明请求 406；需正式 Feed/API/许可 |

Dubai Racing Club 最新 WP 样本为 2026-07-09/07，当前不满足新鲜度；即使满足也因条款
blocked 不进入候选。

## 沙特阿拉伯

| 来源 | 技术/新鲜度证据 | Permission | 结论 |
| --- | --- | --- | --- |
| JCSA | 第一批 adapter technical accepted；精确 Riyadh 时间 | unknown | 主要官方技术候选，明显季节性 |
| Saudi Press Agency | Saudi Cup/JCSA hashtag 页面覆盖好 | blocked | 条款明确禁止自动处理与复制，无书面许可不使用 |
| Arab News | Saudi Cup/horseracing 标签内容丰富 | blocked | 透明请求 Cloudflare 403，不绕过 |
| TDN | Saudi/Riyadh 搜索可用但噪声高 | blocked | 只做既有元数据证据 |
| BloodHorse | Saudi Cup 赛季覆盖高 | unknown | 全球季节性补充 |
| At The Races | Saudi Cup 赛季文章多 | unknown/technical blocked | 当前 client challenge，不绕过 |
| Racing Post Saudi Arabia | 专区覆盖好 | blocked | 透明请求 406；需授权 Feed/API |

沙特采用赛季调度：Saudi Cup/Riyadh 赛季提高发现频率，淡季零稿不是解析失败。

## 澳大利亚

| 来源 | 技术/新鲜度证据 | Permission | 结论 |
| --- | --- | --- | --- |
| Racing Victoria | 第一批 adapter technical accepted，精确 Melbourne 时间 | unknown | 当前主要技术候选，频率不足以单源覆盖 |
| Racing.com | HTTP 200、内容由客户端数据加载 | blocked | 条款限制复制/商业使用；不做 API 逆向 |
| Just Horse Racing | HTML 列表和正文技术可解析、频率高 | blocked | 条款明确禁止未经书面许可复制或复用 |
| Breednet | HTML 列表技术可解析、繁育新闻密度高 | blocked | 条款禁止复制、发布、衍生和商业利用 |
| VRC | 静态新闻可解析 | blocked | copyright 页面要求书面许可 |
| Racing and Sports | 新闻密度高 | unknown/technical blocked | 透明请求 403 |
| Racenet | 新闻密度高 | unknown/technical blocked | 透明请求 403 |
| Punters | 新闻密度高 | unknown/technical blocked | 透明请求 403 |
| Racing Queensland | 官方页面被索引且有日期 | unknown/technical blocked | 透明请求 403 |
| Racing Australia | media releases HTML 可达，低频且详情多为 PDF | unknown | 官方事实补充；本轮不新增 PDF parser |
| TTR Australia & NZ | 首页 HTTP 200、页面前端化 | unknown | 待稳定数据接口与许可 |
| ANZ Bloodstock News | 当前公开索引较旧 | unknown | 暂不作为新鲜主源 |

## 本轮实际联网边界

允许继续实抓：

- permission unknown 且已有 adapter：JCSA、Racing Victoria。
- 本轮方案审核后的 live 范围精确限于上述两源；既有复用来源使用此前 probe/fixture 证据，
  不再联网。
- Canadian Thoroughbred 的列表/详情最小证据已在方案审核前取得；本轮不再联网、不新增
  adapter，只制作不含第三方正文的 synthetic fixture。

禁止联网正文：

- HRI、Woodbine、ERA、TDN、IrishRacing、Dubai Racing Club、Gulf News、The National、
  Saudi Press Agency、Arab News、Racing.com、Just Horse Racing、Breednet、VRC、
  Racing Post。

任何候选均保持本地人工审核；本轮不改变生产许可、来源开关、发布或 QQ。

## 可复核证据索引

核对窗口均为 `2026-07-19 Asia/Shanghai`。本表保存入口与官方政策 URL，不保存或摘抄第三方
正文；`technical` 仅来自透明 User-Agent 的最小响应或此前有界 probe。没有 artifact hash 的
人工页面核对明确记为 `manual-url-evidence`，不得伪装成可复跑 probe artifact。

| Canonical 来源 | 列表/详情入口 | robots / 官方政策 | Technical | Permission | Effective | 证据 |
| --- | --- | --- | --- | --- | --- | --- |
| Canadian Thoroughbred | `https://canadianthoroughbred.com/news/`；详情 `/horse-news/...` | `https://canadianthoroughbred.com/robots.txt`；未找到覆盖本项目用途的明确许可页 | accepted（date-only） | unknown | production_blocked | manual-url-evidence；最新抽样日期 `2026-07-17` |
| HRI | `https://www.hri.ie/news-and-media` | `https://www.hri.ie/terms-and-conditions` | deferred（首轮 artifact 见 rollout） | blocked | production_blocked | 许可结论后零新请求 |
| Woodbine | `https://woodbine.com/news/` | `https://woodbine.com/terms-of-use/` | deferred（首轮 artifact 见 rollout） | blocked | production_blocked | 许可结论后零新请求 |
| TDN canonical | `https://www.thoroughbreddailynews.com/wp-json/wp/v2/posts` | `https://www.thoroughbreddailynews.com/tdn-user-agreement/` | previously accepted | blocked | production_blocked | 只保留许可结论前元数据，正文证据 quarantine |
| Emirates Racing Authority | `https://emiratesracing.com/news` | `https://emiratesracing.com/terms-and-conditions` | deferred（首轮 artifact 见 rollout） | blocked | production_blocked | 许可结论后零新请求 |
| Dubai Racing Club | `https://dubairacingclub.com/news` | `https://dubairacingclub.com/terms-and-conditions/` | accepted（页面/API） | blocked | production_blocked | manual-url-evidence |
| Gulf News | `https://gulfnews.com/sport/horse-racing` | `https://gulfnews.com/about-gulf-news/term-conditions` | accepted（页面） | blocked | production_blocked | manual-url-evidence |
| The National | `https://www.thenationalnews.com/sport/horse-racing/` | `https://www.thenationalnews.com/terms-and-conditions/` | accepted（页面） | blocked | production_blocked | manual-url-evidence |
| JCSA | `https://jcsa.sa/api/news/en/0/12` | `https://jcsa.sa/robots.txt`；未找到覆盖本项目用途的明确许可页 | accepted（2026-07-19 新 artifact） | unknown | production_blocked | `75ecff06…eb5e24`；只允许显式预算 probe |
| Saudi Press Agency | `https://www.spa.gov.sa/en` | `https://www.spa.gov.sa/en/settings/terms-and-conditions` | discovery_only | blocked | production_blocked | manual-url-evidence |
| Arab News | `https://www.arabnews.com/tags/horse-racing` | `https://www.arabnews.com/terms-use` | blocked（403） | blocked | production_blocked | status-only evidence |
| Racing Victoria | `https://www.racingvictoria.com.au/sitemap.xml` | `https://www.racingvictoria.com.au/robots.txt`；未找到覆盖本项目用途的明确许可页 | accepted（2026-07-19 新 artifact） | unknown | production_blocked | `58d1818b…ad3566`；只允许显式预算 probe |
| Racing.com | `https://www.racing.com/news` | `https://www.racing.com/about-us/terms-and-conditions` | client_rendered | blocked | production_blocked | manual-url-evidence |
| Just Horse Racing | `https://www.justhorseracing.com.au/category/news/australian-racing` | `https://www.justhorseracing.com.au/terms-and-conditions` | accepted（页面） | blocked | production_blocked | manual-url-evidence |
| Breednet | `https://www.breednet.com.au/news/` | `https://www.breednet.com.au/terms.html` | accepted（页面） | blocked | production_blocked | manual-url-evidence |
| VRC | `https://www.vrc.com.au/latest-news/` | `https://www.vrc.com.au/copyright/` | accepted（页面） | blocked | production_blocked | manual-url-evidence |
| Racing Australia | `https://www.racingaustralia.horse/MediaAndResources/MediaReleases.aspx` | `https://www.racingaustralia.horse/robots.txt`（`User-agent: *` 禁止该路径范围） | blocked_by_robots | blocked | production_blocked | robots URL evidence |

Racing and Sports、Racenet、Punters、Racing Queensland 的透明请求为 `403`；At The Races
返回 client challenge；均只保留状态与 URL，不绕过、不抓正文。下一次显式 technical probe
必须输出每源固定 `crawled_at`、request ledger、HTTP/final URL、解析计数和 artifact SHA。
本轮 JCSA/Racing Victoria 已分别用精确 listing `1`/detail `2` 预算形成
`75ecff06eb4b72dc04ae42ac138bf68f2177eaac587b8a32c35d568987eb5e24` 与
`58d1818b0ee31fac28777164724bf326bbf62c36cacb39bb9ff00322f8ad3566`，technical 可记
accepted；permission 仍 unknown，effective 不变。

## 2026-07-19 第三批实现清单与实施前验证边界（历史检查点）

本节优先于上方旧 permission 结论。旧表继续作为 terms risk 和历史探测证据。第三批实现
只能证明 adapter/fixture/registry 已落地；当前集成未做最终受控 live probe，不能继承早期
页面核对的 accepted 结论。所有来源均为
`usage_scope=internal_only / public_publish_allowed=false`，并保持生产双关闭。

该段描述 2026-07-19 实施前状态；当前 live 结论以文首第三轮 24-source registry 为准。

| 地区 | 来源 | 获取方法 | 当前集成结论 | 第三批 |
| --- | --- | --- | --- | --- |
| 爱尔兰 | RTÉ Racing | 官方 RSS + 原站详情 | adapter/fixture 已实现；待受控 live probe | 已实现 |
| 爱尔兰 | IrishRacing | HTML 列表 + 详情 | adapter/fixture 已实现；待受控 live probe | 已实现 |
| 爱尔兰 | HRI | HTML 列表 + 详情 | technical blocked；保持关闭 | 既有来源 |
| 加拿大 | Woodbine | 分类 RSS/HTML + 详情 | technical blocked；保持关闭 | 既有来源 |
| 加拿大 | Canadian Thoroughbred | HTML 列表 + 详情 | adapter/fixture 已实现；待受控 live probe | 已实现 |
| 加拿大 | Assiniboia Downs | RSS + 详情 | adapter/fixture 已实现；待受控 live probe | 已实现 |
| 阿联酋 | Dubai Racing Club | RSS，WP API 仅备用 + 详情 | adapter/fixture 已实现；待受控 live probe | 已实现 |
| 阿联酋 | Emirates Racing Authority | HTML/JSON-LD + 详情 | technical blocked；保持关闭 | 既有来源 |
| 阿联酋 | The National Horse Racing | HTML 列表 + 详情 | adapter/fixture 已实现；待受控 live probe | 已实现 |
| 沙特 | JCSA | HTML fragment API + 详情 | technical unknown；保持关闭 | 既有来源 |
| 沙特 | Saudi Press Agency | 搜索/hashtag HTML + 详情 | adapter/fixture 已实现；待受控 live probe | 已实现 |
| 沙特 | Arab News Horse Racing | tag HTML + 详情 | adapter/fixture 已实现；待受控 live probe | 已实现 |
| 澳洲 | Racing Victoria | sitemap + Next detail | technical unknown；保持关闭 | 既有来源 |
| 澳洲 | Just Horse Racing | RSS + 详情 | adapter/fixture 已实现；待受控 live probe | 已实现 |
| 澳洲 | The Straight | RSS + 详情 | adapter/fixture 已实现；待受控 live probe | 已实现 |
| 澳洲 | Racing NSW | RSS + 详情 | adapter/fixture 已实现；待受控 live probe | 已实现 |
| 澳洲 | Tasracing | RSS + 详情 | adapter/fixture 已实现；待受控 live probe | 已实现 |

后续 discovery（不属于第三批实现）：

- Google News RSS 可为五地区分别建立查询，但本轮不实现 collector、不保存 metadata 或
  `NewsArticle`；后续专项必须先锁定聚合链接解析和原站 canonical 门禁。
- Sporting Life、Sky Sports、TDN、BloodHorse、HRN 等全球来源继续复用既有 adapter；
  Ireland/Canada 必须有强地点/赛事信号，不能按来源默认地区误归。

历史调研中仍技术 blocked、不得绕过：

- `403`：Racing Queensland、Racing and Sports、Racenet、Punters、Paulick Report；
- `429`：Racing WA、Australian Turf Club；
- 空/异常响应：Racing SA；
- client/API 不稳定：Racing.com 只作二级人工发现，不作为第三批主源。

这些历史状态不会因 adapter 实现或 fixture GREEN 自动变化。后续 live probe 必须逐源输出固定
`crawled_at`、请求账本、最终 URL/HTTP 状态、解析与时间证据、freshness 分类和 artifact
SHA-256，并汇总最近 6 小时候选/历史/unresolved。完成前所有第三批和既有五源都不可生产
调度，也不得把 dummy/local 结果写成真实外部翻译。
