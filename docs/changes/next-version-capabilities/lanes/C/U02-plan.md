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

## 列表返回合同与安全（root已精化，待原R完整复审）

覆盖三个现有主列表→详情→原列表：race calendar现8键(tab/region/grade/when/year/q/direction/cursor)、horse q/page、news首页page；homepage近期卡片返回news当前page。legacy region不复活，跨实体关系链接沿默认返回。

采用仅本导航使用的紧凑无状态return_nav token（仓库server/scripts检索无现有冲突），Django TimestampSigner独立salt stable.public-list-return.v1，JSON结构精确{v:1,list:races|horses|news,filters:白名单字符串值}。无任意URL/path/Referer/next、无session/cache/DB。Django压缩签名只改变来源导航编码，不改变现有race cursor盐、签名/fingerprint或列表筛选分页规则。token不是授权证明，公开资格/404/CSRF照既有逻辑。

双向闭合：主卡片→详情携短token；详情→精确原列表仍携同token，不把q/cursor重新展开成长浏览器URL。目标列表入口先验证签名、kind/结构/字段及有限预算，只在该请求内展开新的有效QueryDict供既有过滤/分页，禁止重定向为长明文URL。calendar现未知键/污染规范化在token解码及kind检查后使用同一规则，canonical/SEO仍按既有无导航参数输出；原正常query请求继续兼容。首页到race详情可返回news，horse详情只horses，news详情只news；不允许跨类导航目标。

列表token-only：有return_nav时它必须是唯一query键且唯一值，不得混普通业务query或重键。混用、缺签名/过期/错kind/未知字段/非法类型或值整体进入该列表安全默认，不半取token/半取明文。q无独立200上限；原合法q只要整个序列化/实际href可承载就保留，普通列表本身不加cap。page仍1–10位ASCII正整数、year1..9999；tab/region/grade/when/direction和cursor使用现有规则。详情records_page/records_order/关注为本页原功能，独立处理且不能覆盖token内来源；这不将详情参数混入来源列表filters。

发送前先验未压缩JSON bytes≤16384，再签名压缩；用完整最终percent编码href、实际详情/list path、GET与HTTP/1.1及CRLF计算请求行bytes≤3800，低于现Gunicorn4094并留294余量。检查对象包括初始卡片、详情返回/页内状态链接、三列表后续过滤/分页/首页链接，不能只检查token长度或仅去程。过预算不截断q/cursor，不改Nginx/Gunicorn配置；回默认列表的可见返回文案明确“默认列表／筛选条件未保留”。默认降级无来源时也不推断HTTP_REFERER。

消费时outer token ASCII输入≤3800，TimestampSigner先验签及24小时max_age，再base64解码；压缩体用zlib.decompressobj有界输出最多16385字节，超过16384、未到eof、有unconsumed_tail/unused_data/尾随流均拒绝；未压缩体同预算。解析JSON时拒绝重复键，随后拒绝额外/递归字段，逐类型/枚举与来源kind验证，模板默认HTML escaping。不得直接signing.loads未知压缩输入绕过有界解压。嵌套race cursor被外层JSON总预算约束，先按原盐验签/有界解析，再复用现cursor规则；保留旧producer及无TTL合同，不将outer3800单独套到可压缩的大nested cursor。

q200扩展汉字只为保证样例，不宣称所有输入靠压缩都必定足够。压缩率取决内容，任何实际href超预算明确默认返回；q>200只要总预算内仍保留。合法token返回列表后，过滤/分页导航可规范化已验证filters并生成短token以避免再次增长，GET仍只读。过期页/cursor使用原回退规则，不新建业务恢复路径。旧legacy→canonical的301资格/身份不改，仅已验证且最终href预算通过的导航token可随canonical详情携带，canonical标签无token。

## 文件与责任函数

- views.py：_public_today_races/public_news_feed及可选now适配；calendar/horse/news列表到详情与回程列表上下文，一个仅服务三列表的签名/预算/有效GET适配helper。具体helper归属实施前由root按shared views排队；此阶段不新增符号或maps。
- public/feed.html：范围/aria/空态、date-only时刻槽；race_detail.html：指定届次控件与返回；race_calendar.html、horse_index.html、_article_card.html及horse_detail/detail.html：仅主列表往返，不改排序/关联身份/分页算法。
- race_public_time.py、race_information_display.py：本卡只消费、不重写全局合同；models/migrations/Celery/gateway/部署不改。若实现发现必须扩大到时间归一化/权限/身份，先报告root事实，不夹带修复。
- 测试复用tests_legacy.PublicHomeInfoFeedTests/HorseProfilePageMvpTests、test_race_calendar_default_date_window及test_race_information_display_pages已登记模块。新IDs在既有模块追加，最终按diff提mapping proposal，不写共享rules/catalog。

## RED与验证计划

见本线test_cases.md U02段。首个真实RED：固定北京now，D0一场+D6一场普通公开赛事+D7重点，首页应两场且无D7；当前D0/D1逻辑必漏D6。独立时间槽、series多届及列表query往返各先真实RED，不能因现有跨时区能力正确而伪造RED。

两展示开关、跨月跨年/UTC日期差/只有当地日期/无日期/已过时刻/稳定排序/空窗/四场截断与公开资格均为受控fixture；真实网络/provider/生产DB/Redis不参与。只改只读投影/导航无迁移/任务并发；SQLite用于开发，若新增SQL排序表达式按root批准安排固定短PG验SQL/时区集合，不能复用U01旧PG收据。查询有SQL LIMIT，不随全库行数线性物化；返回helper无数据库写入/额外外部访问。

TC-U02中的网络失败重试/宽表/完整手机旅程分别由U04/U05合并验收，不在本卡新增外部服务重试机制。本卡实施后补实际HTML链接/标题/空态与手机读路径证据，不能重跑F04仪表计时冒充人工提效。formal策略未知符号阻断，精确labels/资源窗口交root；实际full/交付由协调者组织。

## 当前状态与下一步

已完成只读盘点及离线fixture设计；未实施、未运行行为RED/GREEN、未改变共享/生产。U02-offline-inventory.json绑定c02文件digest，非生产清单/写入manifest。date-only标签、三类返回及其安全边界已由root确认，下一步交原R方案审，批准后才能按(application)真实RED→实现→相关验证推进。本阶段只新增C文档，按根AGENTS.md边界工作。

## 原R P2及HTTP限制返修证据（2026-10-03）

R-C009-U02-PLAN-001-P2-01（报告commit b590f274）指出旧2048 cursor/4096 URL丢合法扩展汉字；7cb9c137把预算改4096/8192，真实producer最坏2647 JSON bytes/cursor上界3586/相对URL上界6088。该中间稿不是最终方案：root随后核当前ad50 Gunicorn22.0.0 LimitRequestLine.default=4094且无配置override，旧外层query7733在到Django前失败。只增helper预算不足，且详情返回展开原列表URL也有6098字节请求行，双向都须短token。

按root裁定采用上节紧凑token及两端有效GET适配；实际零DB/网络探针使用既有encode/decode cursor、Django签名/QueryDict/urlencode和有界zlib。最长allowed filters、19位PG bigint ID、9999年/最大microsecond time、255字符合法slug：重复200非BMP字符去程985/回程724 bytes；固定seed 200个不同非BMP去程3770/回程3509；随机ASCII700去程2537/回程2276；重复ASCII3000去程965/回程704，全部≤3800<4094且过滤和原签名cursor回环。数值绑定本次收据，签名timestamp改变时重新计算实际href，不能写死旧长度。不同非BMP例是压力正例，不是对所有压缩内容的数学最坏保证。

探针拒绝错误/过期签名、带任意url字段、错list、3801字符outer输入、有效签名但解压超16KiB、尾随压缩流/重复JSON键；解码JSON16384通过/16385拒绝。超过producer JSON预算降级，最终requestline3800允许/3801降级。实际应用helper和页面仍未实施，原生HTTP/Gunicorn旅程尚未实跑，不能把本地编码探针称应用GREEN/生产验收。U02-compact-navigation-probe.json仅保存指标、源码/探针/收据digest，无签名值、密钥、原生产数据。
