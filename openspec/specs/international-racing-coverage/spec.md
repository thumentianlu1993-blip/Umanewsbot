# international-racing-coverage Specification

## Purpose
TBD - created by archiving change expand-international-racing-coverage. Update Purpose after archive.
## Requirements
### Requirement: 系统必须记录赛马地区和原文语言
系统 SHALL 为新闻源、新闻文章和外部赛马数据记录稳定的赛马地区与原文语言。第一期前台可见地区 MUST 包含日本、中国香港、英国、法国和美国；系统 MAY 预留其他地区，但不得在第一期前台 tab 中展示。现有日本数据 MUST 在迁移后被视为日本地区与日文原文。

#### Scenario: 现有新闻回填为日本日文
- **WHEN** 系统完成多地区迁移
- **THEN** 既有 `netkeiba` 与 `JRA` 新闻源和文章 SHALL 具备日本地区和日文原文语言语义

#### Scenario: 新来源必须声明地区和语言
- **WHEN** 系统新增国际新闻源或数据库源
- **THEN** 该来源 SHALL 明确声明地区、原文语言和来源类型，且入库文章或外部数据继承该语义

#### Scenario: 未知地区不进入前台 tab
- **WHEN** 某来源被标记为预留或其他地区
- **THEN** 第一版公开首页地区 tab SHALL NOT 展示该地区入口

### Requirement: 一期国际新闻源必须限定清单和语言
系统 SHALL 在第一期只接入已确认的国际新闻源清单，并限制人工审核新闻正文的原文语言为日文、英文或繁体中文。系统 MUST NOT 将法语新闻正文抓入新闻审核、翻译、自动发布或 QQ 自动推送主链路。

#### Scenario: 日本接入 netkeiba 与 Sponichi
- **WHEN** 一期国际新闻源启用日本扩展
- **THEN** 系统 SHALL 继续使用 `netkeiba` 新闻源，并接入 `Sponichi` 新闻源
- **AND** 系统 SHALL 将其新闻标记为日本地区与日文原文

#### Scenario: 香港接入 HKJC 与 SCMP
- **WHEN** 一期国际新闻源启用中国香港扩展
- **THEN** 系统 SHALL 接入 `HKJC Racing News` 与 `SCMP Racing`，并按实际来源标记英文或繁体中文原文

#### Scenario: 英国接入 Sporting Life 与 Sky Sports Racing
- **WHEN** 一期国际新闻源启用英国扩展
- **THEN** 系统 SHALL 接入 `Sporting Life Racing` 与 `Sky Sports Racing`
- **AND** 系统 MAY 将 `BHA` 作为英国官方公告补充源
- **AND** 系统 SHALL 将其新闻标记为英国地区与英文原文

#### Scenario: 法国只接入英文新闻
- **WHEN** 一期国际新闻源启用法国扩展
- **THEN** 系统 SHALL 接入 `France Galop English News` 与 `TDN` 法国关键词英文新闻进入新闻链路
- **AND** 系统 SHALL NOT 抓取 `Jour de Galop`、`Paris Turf` 或其他法语正文进入新闻审核流
- **AND** 系统 SHALL NOT 将当前返回 403 或反爬不可稳定访问的法国新闻入口作为生产自动来源启用

#### Scenario: 美国接入 TDN 与 Horse Racing Nation
- **WHEN** 一期国际新闻源启用美国扩展
- **THEN** 系统 SHALL 接入 `TDN` 与 `Horse Racing Nation`
- **AND** 系统 SHALL 将其新闻标记为美国地区与英文原文
- **AND** 系统 SHALL NOT 将当前反爬或 403 的美国新闻入口作为生产自动来源启用

#### Scenario: 国际新闻来源键必须防碰撞
- **WHEN** 国际新闻适配器从上游 URL 生成 `source_article_id`
- **THEN** 该键 SHALL 基于完整 URL 生成稳定且低碰撞的来源内去重键
- **AND** 不得只使用 URL 最后一段 slug 作为同一来源内的唯一键

#### Scenario: 公开文章 ID 使用全局自增数字
- **WHEN** 国际新闻入库并公开展示
- **THEN** 用户可见公开详情 URL SHALL 使用本地 `NewsArticle.id` 全局自增数字 ID
- **AND** 来源去重键 SHALL 只用于抓取幂等和上游文章识别，不作为公开文章 ID

#### Scenario: 原始 HTML 不进入轻量翻译 metadata
- **WHEN** 国际新闻适配器解析详情页
- **THEN** 系统 MAY 保存原始 HTML 到 `original_content_html`
- **AND** `translation_metadata` SHALL NOT 保存整页 HTML

#### Scenario: 公开榜单入口应作为排序来源接入
- **WHEN** 一期国际新闻源存在公开、稳定、可慢速抓取的热门、阅读排行、推荐或其他排序型新闻入口
- **THEN** 系统 SHALL 将该入口作为独立榜单来源接入，并记录原站排名
- **AND** 系统 SHALL 使用与普通新闻相同的地区、原文语言、来源去重键和原始 HTML 存储规则

#### Scenario: 混合榜单只保留赛马新闻并保留原站排名
- **WHEN** 排序型入口混有赛马以外的同站内容
- **THEN** 系统 SHALL 过滤非赛马内容
- **AND** 保留下来的赛马文章 SHALL 使用原站排名，不得按过滤后的列表重新编号

#### Scenario: 不稳定或反爬榜单不得作为生产来源启用
- **WHEN** 排序型入口返回 403、反机器人页、空骨架屏或无法确认稳定公开 API
- **THEN** 系统 SHALL NOT 将该入口启用为生产自动榜单来源
- **AND** 仓库文档或测试记录 SHALL 记录对应访问风险

### Requirement: 香港 HKJC 外部数据必须支持受控导入
系统 SHALL 提供中国香港 `HKJC` 外部赛马数据的受控导入能力。导入 MUST 支持按赛日、单场比赛和单匹马执行，并沿用外部数据导入的限速、抖动、批量上限、单来源互斥、幂等 upsert、断点续跑、失败隔离和 dry-run 规则。

#### Scenario: 导入 HKJC 赛日比赛
- **WHEN** 运维人员指定 HKJC 赛日执行导入
- **THEN** 系统 SHALL 抓取并保存该赛日可发现的比赛、出马和赛果摘要，并保留原始 payload

#### Scenario: 保存 HKJC 比赛字段
- **WHEN** HKJC 来源返回比赛信息
- **THEN** 系统 SHALL 保存比赛日期、马场、场次、比赛名称、班次或等级、距离、场地、跑道、奖金、Going、天气或场地状态、开跑时间和原始 payload 中的额外字段

#### Scenario: 保存 HKJC 出马字段
- **WHEN** HKJC 来源返回出马表
- **THEN** 系统 SHALL 保存马名、外部马匹标识、档位、骑师、练马师、负磅、装备、评分、马主或可用连接信息和原始 payload

#### Scenario: 保存 HKJC 赛果字段
- **WHEN** HKJC 来源返回赛果
- **THEN** 系统 SHALL 保存名次、完成时间、距离差、赔率、沿途位置、分段时间、骑师、练马师、档位和原始 payload

#### Scenario: 保存 HKJC 马匹字段
- **WHEN** HKJC 来源返回马匹资料
- **THEN** 系统 SHALL 保存英文名、中文名、外部马匹标识、父系、母系、出生日期或年龄、产地、性别、毛色、马主、练马师、累计赛绩和原始 payload

#### Scenario: 从 HKJC 派生马名索引
- **WHEN** HKJC 出马表、赛果或马匹资料包含可信马名
- **THEN** 系统 SHALL 创建或更新本地外部马名索引，并保留英文名、中文名和外部马匹标识之间的关系

#### Scenario: HKJC payload 超过批量上限时失败
- **WHEN** 运维人员以 commit 模式导入 HKJC payload
- **AND** payload 中比赛数量超过 `max_races` 或马匹数量超过 `max_horses`
- **THEN** 系统 SHALL 拒绝本次导入并返回明确错误
- **AND** 系统 SHALL NOT 静默截断、部分写入或创建成功导入 run

### Requirement: 欧美数据库源必须先做受控 spike
系统 SHALL 在第一期对美国、英国和法国数据库源执行受控技术 spike，而不是直接承诺全量正式导入。spike MUST 使用小样本、限速和 dry-run 或等价只读方式，输出字段覆盖、入口参数、访问限制、解析风险和后续实现建议。spike MUST NOT 加入自动调度、正式导入队列或生产网络导入流程；spike MUST NOT 写入正式外部数据表，除非后续独立 change 明确批准。

#### Scenario: Equibase spike 输出风险报告
- **WHEN** 系统执行美国 `Equibase` 数据源 spike
- **THEN** spike 产物 SHALL 说明 entries、results、charts、horse profile 的可抓字段、访问限制、反爬风险和后续正式实现建议

#### Scenario: 英国数据源 spike 输出字段矩阵
- **WHEN** 系统执行英国 `Sporting Life + BHA` 数据源 spike
- **THEN** spike 产物 SHALL 说明 racecards、results、horse profile、official horse search 和 stewards 或监管信息的字段覆盖和缺口

#### Scenario: 法国数据源 spike 不抓法语新闻正文
- **WHEN** 系统执行法国 `France Galop` 数据源 spike
- **THEN** spike 产物 SHALL 只评估结构化赛程、报名、出马、赛果和马匹资料入口
- **AND** 不得把法语新闻正文纳入新闻审核链路

#### Scenario: spike 不写正式数据表
- **WHEN** 系统执行任一欧美数据库源 spike
- **THEN** 系统 SHALL NOT 创建正式外部比赛、出马、赛果、马匹或马名索引记录
- **AND** 如需保存样本解析结果，只能保存到隔离 fixture、临时文件或仓库文档报告

#### Scenario: spike 报告记录请求边界
- **WHEN** spike 完成
- **THEN** 仓库文档 SHALL 记录样本 URL、请求次数、限速设置、失败情况、字段覆盖和后续正式导入建议

### Requirement: 导入的比赛和赛果数据不得被误当作前台赛果产品
系统 SHALL 允许第一期保存比赛、出马、赛果和马匹结构化缓存，但这些数据只服务于外部马名索引、翻译保护、术语候选发现、文章关联和后续项目准备。系统 MUST NOT 在本变更中实现公开比赛页、赛果页、马匹页或完整赛程产品。

#### Scenario: 外部赛果只作为缓存
- **WHEN** HKJC 或后续数据源导入赛果
- **THEN** 系统 SHALL 将赛果保存为外部缓存，并不得自动发布为前台赛果页面

#### Scenario: 新闻文章可以关联外部数据
- **WHEN** 新闻文章提及已导入的比赛或马匹
- **THEN** 系统 MAY 使用外部缓存辅助识别和候选发现，但公开文章详情页仍以新闻内容为主

### Requirement: 法国 TDN 关键词来源必须使用真实发布时间并过滤历史搜索结果
系统 SHALL 在处理法国 `TDN` 关键词英文新闻来源时，使用 TDN post API 的真实发布时间作为文章发布时间，并过滤搜索接口返回的历史旧文。系统 MUST NOT 因 search item 缺少日期而把历史文章标记为当前时间。

#### Scenario: search item 通过 post API 补真实日期
- **WHEN** `tdn_france_broad` 从 TDN search API 获得只包含 `id/title/url` 且不包含 `date/date_gmt` 的 search item
- **THEN** 系统 SHALL 使用 search item 的 `id` 或 `_links.self` 拉取对应 post API
- **AND** 系统 SHALL 从 post API 的 `date_gmt` 或 `date` 解析文章真实发布时间

#### Scenario: 历史旧文被新鲜度过滤
- **WHEN** TDN search API 返回一篇真实发布时间早于允许新鲜度窗口的历史文章
- **THEN** 系统 SHALL 跳过该文章
- **AND** 系统 SHALL NOT 创建或更新 `NewsArticle`
- **AND** 系统 SHALL 在抓取或探测摘要中保留跳过原因

#### Scenario: 无法取得真实 post 日期时跳过
- **WHEN** TDN search item 的 post API 不可访问、缺少 `date/date_gmt` 或日期无法解析
- **THEN** 系统 SHALL 跳过该条 search item 并继续处理同一轮其他条目
- **AND** 系统 SHALL NOT 将该文章发布时间兜底为当前时间

#### Scenario: 真实近期文章仍可入库
- **WHEN** TDN search item 的 post API 返回真实发布时间且该时间在允许新鲜度窗口内
- **THEN** 系统 SHALL 按既有 TDN canonical 去重规则创建或更新文章
- **AND** 入库文章 SHALL 保留法国来源配置语义

### Requirement: 国际英文来源必须支持按内容归属地区
系统 SHALL 支持将英文国际来源或英国来源中的文章按内容实体归属到日本、中国香港、英国、法国或美国，而不是仅按来源默认地区入库。来源默认地区 SHALL 只作为无法识别赛事或核心实体时的 fallback。

#### Scenario: 英国来源报道法国赛事归属法国
- **WHEN** 英国英文来源文章明确报道法国境内赛事
- **THEN** 系统 SHALL 将法国纳入该文章地区归属
- **AND** 系统 SHALL NOT 仅因来源默认地区是英国而只归属英国

#### Scenario: 英国来源无明确实体时归属英国
- **WHEN** 英国英文来源文章没有明确赛事地或核心实体地区
- **THEN** 系统 SHALL 将英国作为文章主地区

#### Scenario: 全球英文来源报道香港马归属香港
- **WHEN** 全球英文来源文章核心对象是香港马、香港骑师或香港练马师
- **THEN** 系统 SHALL 将中国香港纳入该文章地区归属

### Requirement: 法国新闻池必须保持原文可审核
系统 SHALL 继续禁止法语正文进入新闻审核、翻译、自动发布或 QQ 自动推送主链路。法国新闻池 MAY 接收英文来源中的法国赛事、法国赛果、法国赛马生态、法国马、法国骑师、法国练马师、法国马场、France Galop 或法国拍卖/育马相关内容。

#### Scenario: 法语正文不进入主链路
- **WHEN** 候选来源文章正文语言为法语
- **THEN** 系统 SHALL NOT 将该文章纳入新闻审核、自动发布或 QQ 自动推送主链路

#### Scenario: 英文法国生态内容进入法国池
- **WHEN** 英文文章明确报道 France Galop、Longchamp、Deauville、Chantilly、Arqana、法国育马、法国拍卖或法国马场相关内容
- **THEN** 系统 SHALL 允许该文章进入法国新闻池
- **AND** 系统 SHALL 保留命中的法国实体作为归属证据

#### Scenario: 法国实体海外参赛多地区归属
- **WHEN** 英文文章报道法国马、法国训练马、法国骑师或法国练马师在海外赛事中的表现
- **THEN** 系统 SHALL 将法国纳入文章地区归属
- **AND** 系统 SHALL 将比赛发生地区也纳入文章地区归属

### Requirement: 香港新闻池必须支持宽口径内容
系统 SHALL 允许中国香港新闻池接收赛事新闻、赛前展望、赛果简报、HKJC 官方通知、赛程/出赛表/装备/兽医报告、从化训练、香港马海外远征、香港骑师/练马师动态、香港国际赛、拍卖、售马、马主活动、人物特写和可审核英文/繁中来源文章。

#### Scenario: HKJC 官方通知进入香港池
- **WHEN** HKJC 官方来源发布兽医报告、装备更新、赛程通知或 racecard update
- **THEN** 系统 SHALL 允许该内容进入中国香港新闻池
- **AND** 系统 SHALL 按内容类别决定自动发布和 QQ 资格

#### Scenario: 香港马海外远征进入香港池
- **WHEN** 英文或繁中文章报道香港马在海外赛事参赛或获奖
- **THEN** 系统 SHALL 将中国香港纳入文章地区归属
- **AND** 系统 SHALL 将比赛发生地区也纳入文章地区归属

### Requirement: 新闻内容类别必须标准化
系统 SHALL 为新增和既有国际新闻文章保存标准内容类别。首期类别 MUST 至少包含 `news`、`preview`、`result_brief`、`official_notice`、`racecard_update`、`tips`、`feature`、`sales_breeding` 和 `other`。

#### Scenario: 赛前展望分类
- **WHEN** 文章主要介绍即将举行赛事的参赛马、赛前形势或焦点
- **THEN** 系统 SHALL 将内容类别保存为 `preview`

#### Scenario: 赛果简报分类
- **WHEN** 文章主要报道赛事结果、冠军、名次或赛后短评
- **THEN** 系统 SHALL 将内容类别保存为 `result_brief`

#### Scenario: 投注倾向内容分类
- **WHEN** 文章主要包含选号、赔率、best bets、NAP、each-way 或 free bet 表达
- **THEN** 系统 SHALL 将内容类别保存为 `tips`

### Requirement: 国际新闻来源必须声明可验证的正文边界
每个进入生产自动抓取的国际新闻适配器 SHALL 声明可离线测试的正文选择器和来源级清理规则。正文节点缺失 SHALL 被视为页面结构漂移或解析失败，不得通过整页文本兜底掩盖。

#### Scenario: 新增国际新闻来源
- **WHEN** 系统新增一个可进入审核、翻译或自动发布链路的国际新闻来源
- **THEN** 该来源 SHALL 提供正文选择器 fixture 测试
- **AND** 测试 SHALL 证明导航、页脚和来源模板不会进入正文

#### Scenario: 既有国际来源页面结构漂移
- **WHEN** 已启用来源的页面不再匹配已验证正文结构
- **THEN** 系统 SHALL 将该文章留在不可发布或人工处理状态
- **AND** 抓取摘要 SHALL 提供足以定位来源和选择器的失败信息
