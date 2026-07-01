## Why

UmaFans 当前核心内容链路仍以日本新闻源为中心。后续要服务中文赛马用户，需要把内容覆盖扩展到日本、中国香港、英国、法国和美国，同时不能把新的地区、语言、数据库导入和 QQ 群推送策略混成一套难以灰度的全局行为。

本变更用于把“多地区赛马资讯平台”的第一期边界写清楚：先让系统具备多地区、多原文语言、多来源类型的承载能力；前台提供地区 tab；后台术语库不再只按日文假设工作；QQ 自动推送改为按群配置地区和范围；外部数据库导入先完整落地 HKJC，并对欧美数据源做受控 spike。

## What Changes

- 为新闻源、文章和外部赛马数据引入地区与原文语言语义，第一期地区为日本、中国香港、英国、法国、美国，其他地区预留但不在前台展示。
- 一期新闻源范围：
  - 日本：`netkeiba`、`Sponichi`
  - 中国香港：`HKJC Racing News`、`SCMP Racing`
  - 英国：`Sporting Life Racing`、`Sky Sports Racing`；`BHA` 作为官方公告补充源
  - 法国：`France Galop English News`、`TDN` 法国关键词英文新闻；不得抓取法语新闻正文进入审核流
  - 美国：`TDN`、`Horse Racing Nation`
- 对新增新闻源补充“排序型入口”策略：若来源存在公开、稳定、可慢速抓取的热门/阅读排行/推荐榜单，应作为独立 `source_mode=access` 或等价榜单源接入，并记录原站排名；本轮确认 `Sponichi` 具备公开 `ニュースランキング`，可先接入。
- 一期新闻正文原文语言仅支持 `ja`、`en`、`zh-hant`；法国法语来源只能作为结构化数据或后续候选，不进入新闻翻译审核主链路。
- 公开首页新增地区 tab：综合、日本、中国香港、英国、法国、美国；综合流第一期使用已发布文章倒序，不做复杂打散。
- 术语库从“每条术语绑定一种原文语言”升级为“一个正式术语概念 + 多语言原文别名”：`TermEntry` 表示标准中文术语概念，`TermAlias` 或等价结构保存日文、英文、繁体中文原文名与别名；现有物理字段继续兼容旧代码，但不得作为长期概念边界。
- QQ 自动推送从全局范围配置扩展为群级配置；每个 `PushTarget` 可以配置允许地区、推送范围和重点策略，不同群可以收到不同地区或不同范围的新闻。
- 外部数据库导入第一期正式实现 HKJC；Equibase、英国 `Sporting Life + BHA`、法国 `France Galop` 作为技术 spike 输出字段覆盖、抓取入口、限速风险和后续实现建议。
- HKJC 正式提交导入必须执行批量上限硬校验；payload 超过 `max_races / max_horses` 时直接失败，不静默截断或部分写入。
- 公开文章 URL 和用户可见文章 ID 继续使用 `NewsArticle.id` 这个全局自增数字；抓取入库仍必须保留来源稳定键，国际新闻源的来源键必须基于完整 URL 防碰撞，不能只依赖 URL 最后一段 slug。
- 多语言术语匹配必须按文章原文语言选择对应 `TermAlias`；命中后回到同一个 `TermEntry` 概念。重点马、赛事优先级、自动标签、发布校验等信号不得跨语言误匹配，但允许同一匹马的日文名、英文名、繁中名合并到同一个正式术语概念。
- 比赛/赛果/马匹前台页面不在本变更实现范围内；导入的比赛、出马、赛果和马匹数据只用于外部缓存、马名识别、翻译保护、候选术语发现和后续大项目准备。

## Capabilities

### New Capabilities

- `international-racing-coverage`: 定义多地区新闻源、支持语言、HKJC 外部数据导入、全球数据源 spike 和本期非目标边界。

### Modified Capabilities

- `public-home-info-feed`: 增加地区 tab 与地区过滤信息流。
- `termbase-and-race-priority`: 将正式术语库从“日文原词”语义扩展为多原文语言术语语义，并约束语言相关识别规则。
- `qqbot-auto-push`: 将 QQ 自动推送范围和地区过滤从全局配置扩展为群级配置。

## Impact

- 代码范围：`server/stable/models.py`、migrations、`services/`、`adapters/`、`tasks.py`、后台 forms/views/templates、公开首页 views/templates/static、Django Admin。
- 数据迁移：预计需要为 `NewsSource`、`NewsArticle`、外部数据模型、`TermEntry`、`TermCandidate`、`PushTarget` 增加地区/语言/群级配置字段；现有日文数据必须自动回填为日本/日语。
- 配置：QQ 推送保留全局开关，但范围、地区和重点策略应迁移到群级配置并提供兼容默认值。
- 测试：覆盖地区元数据、前台 tab、术语多语言、HKJC 导入、QQ 群级过滤和 spike 输出。
- 上线前 review：完成最终源清单实现后，必须执行一次整体 review，重点检查代码、内容链路和生产灰度/回滚路径。
- 运维：数据库导入仍必须遵守低频、限速、抖动、可暂停、可恢复和同来源互斥规则；本变更不要求立即生产部署。
