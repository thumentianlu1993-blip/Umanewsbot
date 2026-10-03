# C009 / U02 方案（口径已由协调者确认，待原R审核）

2026-10-03 Asia/Shanghai。只读基线c02dd9fb4cde31034a9e37ba957de8f394a05854；承接tasks U02、UG-03/TC-U02，DDL10/09 18:00。依F05固定事实报告及F05-public-evidence.json，观察时间02:07–02:10；本次不复访生产。Q01/C006/Q02/F04已审内容不重做，模型/共享maps/业务文件零修改。

## 已确定范围与代码缺口

原需求回写证据在docs/reports/2026-10-02-backlog-evidence-reconciliation.md第2节/B05/B28：今天起一周=今天加后6天，最多4条，首页缺可靠时刻不显示待定；移除赛事详情右上年份切换。全站未知时刻留空不是原指令，保持详情现有未知表达。tasks另明确列表返回保条件；H07档案完整度排序/U03身份去重不属本卡。

当前首页_public_today_races限4但只取今天/明天，空则回填更远P0/P1/featured；feed hero标题/aria仍今日赛事，time通过race_field投影会输出待定。race_detail对已审series且多届公开展示右上switcher；返回calendar/horse/news列表均固定裸路径。F05未做这三项新的生产行为验收，不能将代码缺口当本次已观察线上失败。

## 已确认口径（2026-10-03 root确认；审核前不实施）

1. 首页面板叫“近期赛事”，说明“今天起七天”；D0..D6闭区间，以单次captured aware now投影Asia/Shanghai日期。不是当前周一到周日，不是未来168小时。包含今天已过时刻及完赛：原日窗口和冠军展示如此，原需求没有“只未来”过滤；既有状态/已确认winner逻辑维持。取消/延期不新增过滤，依旧显示原状态。
2. 复用annotate_public_time/public_time：有可靠instant按北京时间跨月/跨年；date-only按既有当地local_date参与同日历区间，clock为空，不推断北京时间。日期meta明确“当地赛日”，时刻槽完全留空。错误时区/冲突且public_date缺失不捏造日期；已明确只有当地日期的对象不一概丢弃。协调者已确认该呈现及三类列表返回范围。
3. 按public_date升序、public_start_time升序NULLS LAST、id升序，在SQL内取最多4；不加重点/等级优先，不把未知时间写成00:00，不先全表Python过滤再截断。日期第一意味着今日date-only仍在明日已知赛前；同日已知时刻优先、同刻稳定id。SQLite/PG NULL排序差异用显式排序消除。
4. 无区间赛事就保留标题与“今天起七天暂无已登记赛事”的空态/完整日历入口，不取D7以后补满4条，不把无登记当实际无赛事。旧fallback标志不再参与标题或查询；可最小保留内部返回tuple False兼容既有caller。独立右栏next_key_race与calendar本周G1焦点不在此范围，不改为滚动七天。
5. 只删除race_detail右上details.race-year-switcher，静态event.year保留；series历史冠军、year身份/registry、日历年份筛选不删。必要时去仅服务该控件的series_events查询，但不能删除_series_history_winners或系列数据。无档案排序/duplicate合并/生产数据修正。

捕获now只为此次首页请求；可给_public_race_status_label加可选now参数供首页传入，默认行为保持，避免窗口与状态跨午夜分叉。不得借此重写RG生命周期/赛果确认规则。

## 列表返回合同与安全

只覆盖三个现有主列表→对应详情：race calendar保存现8键(tab/region/grade/when/year/q/direction/cursor)，horse保存q/page，news首页保存page；新闻/马匹legacy region已被_redirect_legacy_region剥离，不复活任何旧筛选。homepage近期卡片可返回首页当前page。跨实体新闻/马匹/赛事关系链接沿默认返回，关系导航另属L线。

列表主卡片传return_to为经过当前列表规范化的相对URL；详情使用允许的对应list path/query重建，不信任HTTP_REFERER或任意next。只允许精确/races/、/horses/、/等对应来源，拒绝scheme/netloc（包括同host absolute）、//、反斜杠、控制字符/CRLF、错类路径、未知/递归导航键。使用urlsplit/QueryDict、每键确定单值与urlencode、模板默认转义；不对不可信字符串二次decode，不接收/admin或任意本站路径。

安全校验拟采用有限输入预算：return_to解码后的总长度最多8192字符，q最多200个Unicode码点，cursor最多4096字符；page仅1至10位ASCII正整数，year仅1至9999的ASCII整数。tab/region/grade/when/direction复用现有枚举值；cursor复用既有签名、筛选指纹和复合位置校验，不另建身份规则。重复query键拒绝，非法值及超预算整体退回对应默认列表，不截断后猜测。HTTP外层request.GET先正常解码return_to一次，得到带urlencode内层query的相对URL；urlsplit分离path后，QueryDict再按该内层query解码一次，q/cursor保原语义。这是两层独立编码，不是对一个值重复unquote。path必须精确白名单，拒绝其编码路径/残留编码分隔符、scheme/netloc、控制字符；查询q的正常percent编码和字面%文本不能被全URL扫描误拒。不得对已解析值再unquote，模板默认转义。此预算只约束导航元数据，不改变列表本身查询合同。

非法/缺失来源降级现有默认返回，不影响详情200/404资格。有效q中文/空格/page/cursor保语义，不要求字节顺序；回到过期页仍用既有分页/游标安全回退。浏览器Back自然行为不替代可见返回链接。URL canonical/SEO标签保持无return_to；已有legacy→canonical的资格/身份与301规则不改，可仅携带经过验证的导航参数，禁止变为开放重定向。详情records_page/records_order/关注POST不会覆盖来源返回；不动cookie/token/订阅能力。

## 文件与责任函数

- views.py：_public_today_races/public_news_feed及可选now适配；calendar/horse/news列表到详情上下文，建议一个小型公开列表返回校验helper。具体helper归属实施前由root按shared views排队；此阶段不新增符号或maps。
- public/feed.html：范围/aria/空态、date-only时刻槽；race_detail.html：指定届次控件与返回；race_calendar.html、horse_index.html、_article_card.html及horse_detail/detail.html：仅主列表往返，不改排序/关联身份/分页算法。
- race_public_time.py、race_information_display.py：本卡只消费、不重写全局合同；models/migrations/Celery/gateway/部署不改。若实现发现必须扩大到时间归一化/权限/身份，先报告root事实，不夹带修复。
- 测试复用tests_legacy.PublicHomeInfoFeedTests/HorseProfilePageMvpTests、test_race_calendar_default_date_window及test_race_information_display_pages已登记模块。新IDs在既有模块追加，最终按diff提mapping proposal，不写共享rules/catalog。

## RED与验证计划

见本线test_cases.md U02段。首个真实RED：固定北京now，D0一场+D6一场普通公开赛事+D7重点，首页应两场且无D7；当前D0/D1逻辑必漏D6。独立时间槽、series多届及列表query往返各先真实RED，不能因现有跨时区能力正确而伪造RED。

两展示开关、跨月跨年/UTC日期差/只有当地日期/无日期/已过时刻/稳定排序/空窗/四场截断与公开资格均为受控fixture；真实网络/provider/生产DB/Redis不参与。只改只读投影/导航无迁移/任务并发；SQLite用于开发，若新增SQL排序表达式按root批准安排固定短PG验SQL/时区集合，不能复用U01旧PG收据。查询有SQL LIMIT，不随全库行数线性物化；返回helper无数据库写入/额外外部访问。

TC-U02中的网络失败重试/宽表/完整手机旅程分别由U04/U05合并验收，不在本卡新增外部服务重试机制。本卡实施后补实际HTML链接/标题/空态与手机读路径证据，不能重跑F04仪表计时冒充人工提效。formal策略未知符号阻断，精确labels/资源窗口交root；实际full/交付由协调者组织。

## 当前状态与下一步

已完成只读盘点及离线fixture设计；未实施、未运行行为RED/GREEN、未改变共享/生产。U02-offline-inventory.json绑定c02文件digest，非生产清单/写入manifest。date-only标签、三类返回及其安全边界已由root确认，下一步交原R方案审，批准后才能按(application)真实RED→实现→相关验证推进。本阶段只新增C文档，按根AGENTS.md边界工作。

## 原R P2导航预算返修（纯文档，待复审）

原4096 URL/2048 cursor预算不足，扩展汉字200字符合法筛选会被误降级。实际基线Django5.2.1既有encode_race_calendar_cursor/decode、JSONSerializer/signing以及QueryDict/urlencode作无DB/网络诊断：q=𠮷×200、最长允许region united_kingdom、tab all/grade g3/when upcoming/year9999/direction future、最大PG bigint id9223372036854775807、date9999-12-31/time23:59:59.999999；JSON2647字节，当前cursor3581字符，相对URL6083字符，HTTP外层query7733字符。真实内外层解析后q与签名cursor完全回环。合成签名值/密钥不写文档，长度和源码digest见U02-navigation-budget.json。

有限上限推导：合法Unicode码点JSON ensure_ascii最大12 ASCII字节（代理对），200字=2400；UTF8百分号编码同为每码点最多12 URL字符。其它filters取各最长已允许枚举/year4位，key用19位有符号bigint正最大值、日期10/时刻15字符，2647字节是当前producer紧凑JSON最坏长。unpadded urlsafe base64≤ceil(4×2647/3)=3530；签名SHA256为43字符、2个冒号，加最多11位base62正64bit timestamp，cursor≤3586。URL键名/枚举和内层percent编码冒号均计入，相对URL≤6088。因此采用4096 cursor与8192已解HTTP外层return_to，留510及2104字符余量；不是将外层完整请求URL限制为8192。未来producer版本/签名算法/字段或枚举扩大需重新推导，不能悄悄截断。

calendar和horse既有q未设200限制；此预算仅明确导航保条件保证q≤200码点，>200原列表查询仍照常，仅来源导航安全回默认，不能给列表新增200上限或修改签名fingerprint。page10位/year1..9999保持原方案。若需要保证更长q的返回保真，须root显式扩大有限预算与验收范围。

补充设计正例为200扩展汉字/最大filters和合法签名cursor真实主列表→详情→返回，内层与外层urlencode后一次各层解析，q/cursor/page语义一致；刚超cursor4097、decoded return_to8193、q201负例安全默认，不影响详情资格。当前诊断只验证既有序列化/回环和长度，拟新增导航helper/页面未实施，负例guard尚未行为验证。
