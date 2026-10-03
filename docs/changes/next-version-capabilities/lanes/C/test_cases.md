# U01 实施测试设计

受审依据：U01-plan@2919dd35、协调者C-003派单与U01-offline-cases.json；承接总规格TC-U01。当前只读查询，无模型约束/迁移/Celery投递行为变更，不引入额外生产动作。既有未知/冲突数据保留待核实，GET不持久写等级字段。

| 用例 | 验收与mutation |
|---|---|
| U01-RED-01 | 同一德国2025G1原文/空规范字段在未筛选与G1筛选均可见且卡片g1颜色；两展示开关覆盖。捕获仅修模板、继续normalized_grade__in、取页后过滤 |
| U01-PARITY | 全部33合成场景及Unicode/空白/已核验JRA源上下文扩展；SQL代码与Python event_grade_field.code相等，未知/冲突排除分级查询。捕获宽松substring、忽略存储冲突、未证LocalG1升级、错误移除赛事名后缀 |
| U01-VISIBILITY | published/canonical exclusion/地区年份交集保持；隐藏/duplicate事件不因等级别名被公开。捕获OR优先级扩大集合 |
| U01-PAGING | 混合等级跨页、默认日期窗口、year/q游标；筛选在LIMIT前，游标不混筛选条件。捕获全表Python过滤/先分页再过滤 |
| U01-FOCUS | 历史重点G1/G2集合及weekly focus传入events/独立query分支；当前priority规则保持。捕获遗留normalized-only消费者 |
| U01-NO-WRITE | GET前后原始等级/normalized/source_refs一致；使用querycount确认无逐行DB查证。捕获隐式补字段及N+1 |
| U01-COMPAT | flag两状态等级一致，既有距离/单位legacy开关保持；卡片文字/颜色/详情等级相同。捕获为修等级开启全局单位规范化 |
| U01-PG | 固定Git树/Linux无外网容器/PostgreSQL16 native expression语义与SQLite诊断分开；数据库表达式不兼容即失败并报告，不新增schema或扩大运行环境 |

正常外部恢复、超时、Celery重投等不在U01新增行为范围；生产取数不用于自动测试。保存版本保护仍由既有路径保证，U01只消费读字段。未知后端/SQL失败不能回退全表后过滤。返回旧代码SHA即可回滚代码，数据字段不需要反向迁移。

首个RED最小测试在现有 `test_race_information_display_pages.PublicGradeFilterParityTests`；从真实断言漏对象开始，再同例GREEN与受影响计划回归。宿主SQLite结果只作诊断，不作为固定Linux交付证据。测试模块沿既有catalog，修改后执行影响计划；每批最多200项，共享VM总最多2批。

## C008 / Q02 UI/action实施测试设计

依据固定Q02@7e3f及原R C007 APPROVED@e97406d7。仅admin/views/console模板，没有事务/任务/数据库约束或部署实现变化；五旧task已有终止审计，保持不动。复用既有权限/CSRF与Q01发送安全边界。

| 用例 | 真实断言与mutation |
|---|---|
| Q02-ADMIN-HIDE | false真实Admin列表/详情无push URL及PUSH_READY动作，翻译仍存在；历史PUSH状态标明历史、不重写值；捕获仅改文案/只藏列表不藏fieldset/把旧失败当可重试 |
| Q02-ACTION-GUARD | false旧action伪造POST与直接callback都不改变status/workflow/publication，不入队；捕获只过滤get_actions缺callback guard |
| Q02-TRUE | true原push URL/菜单保留，原action只写PUSH_READY；不发送真实消息；捕获删除兼容或改网页workflow |
| Q02-QQ-WINDOW | false QQ详情无rerun/发送preview链接，明确停用且历史target决策可读；直达preview无预计QQ文章，不调用选择器，不修改决策/rerun |
| Q02-PUBLISH | false publish详情preview/rerun仍存在，原QQ shutdown publish测试与区域测试覆盖业务；捕获模板误把全部窗口停用 |
| Q02-REGION | false地区QQ计数改历史/停用说明且数字不丢；true既有等待展示保留；捕获删除计数或把停用作为仍可重试 |
| Q02-PERMISSIONS | 匿名重定向、非staff403、缺对象404、CSRF缺token403、rerun GET405；历史Admin数据注册/view权限保持，无新权限体系 |
| Q02-REGRESSION | 既有Q01普通停用/邮件与enabled Admin/窗口回归按实际diff选测；不重跑已审PG竞争，代码未变不迁移旧PG证据为新实现 |

宿主清env/禁dotenv/:memory:SQLite、memory broker/locmem邮件与缓存，全mock OneBot。先最小真实行为RED后UI实现，再同例GREEN及对应回归；新case注册既有stable.tests_legacy，mapping建议单独报告，不修改共享rules/catalog。LinuxPG窗口若另需只能root分配。本实施不改变settings/Compose/调度/生产停用/外发。


## C009 / U02 实施前测试设计（待原R方案审，未执行）

依据U02-plan、UG-03/TC-U02与离线inventory，三个列表返回/date-only呈现已由root确认。无模型约束/迁移、Celery/并发状态变更；只读公开资格/安全返回及SQL排序兼容需要验证，当前不制造运行通过。

| 用例 | 断言与要捕获的mutation |
|---|---|
| U02-RED-WINDOW | 冻结BJ now，D0普通+D6普通+D7重点；只包含D0/D6，标题/aria近期且范围七天；捕获仍D0/D1/远期fallback/只改标题 |
| U02-TIME-BOUNDARY | D-1/D0/D6/D7精确边界，跨月跨年、UTC与BJ不同日、London/Auckland源当地日期；clock按可靠instant，source字段不写；捕获按UTC/本周/edition year筛窗口 |
| U02-TODAY | 今日已过时刻、正在进行、已确认完赛、取消/延期保现状态，未知winner不伪造；request跨午夜仍同一now；捕获新增未来-only或混状态时钟 |
| U02-DATE-ONLY | 各地区仅local_date纳入约定窗口、日期meta当地赛日/clock槽空；两信息开关均无待定/00:00；冲突/未知时区且无public_date不捏造日期；捕获只改label却被race_field回填 |
| U02-LIMIT-SORT | 同日6场混已知/未知clock、同刻稳定id、跨日date优先，SQL取4；SQLite/PG同集合；捕获NULL默认差异/priority抢位/取页后过滤 |
| U02-EMPTY | 空库、仅远期重点、仅无日期、仅隐藏/active canonical duplicate：固定空态/日历入口，零fallback；没有可靠日期不说实际无赛；捕获填满/隐藏整个面板 |
| U02-EDITION | approved series+两届公开仍无右上switcher；静态year、历史冠军和calendar年份选择/筛选工作；捕获只删单届、误删历史身份/年份能力 |
| U02-RETURN | race八键(含year/q/cursor)、horse q/page、news page，列表主卡片→详情→返回保持语义；home卡片return homepage；关注/records分页不丢来源 |
| U02-RETURN-SAFE | external/samehost absolute、//、javascript、\/CRLF、编码混淆/递归键/错类path、未知键、重复键、非法枚举/page/year、q/cursor/URL长度超限安全降级；中文q与HTML字符默认转义，非法来源不改变404/公开资格；捕获开放redirect/XSS/双decode |
| U02-LEGACY | legacy→canonical仍301/公开资格/clean canonical，已验证来源参数仅导航携带；过期cursor/page既有回退；捕获改身份或绕资格 |
| U02-REGRESSION | 新闻公开与曝光规则、horse现排序/records页、calendar默认锚点/年份/等级/本周焦点不变，右栏独立重点不误改；fixture不触第三方/真实队列 |

建议在既有模块追加精确case；首轮只专项RED，再同例GREEN与实际diff回归。不得提前实跑“未来实现”或将F05时间限定样例当新生产验收；PG/大容器只有root分配。TC-U02长表/网络失败旅程与U04/U05合并，H07/U03不夹带本卡。
