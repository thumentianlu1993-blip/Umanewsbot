# 测试与验收合同

## 0. 预声明假设与通过门槛

- H1：每个启用地区，TRA 返回空且至少一个非 TRA 来源提供合格身份时，覆盖目标最终有且仅有 1 个 enrollment；7 桶 fixture 全通过，重复 event/enrollment=0。
- H2：A→B、B→A、同轮及并发到达，已核验同场的 event ID 不变；不同场误合并=0，所有负例零 canonical 写入。
- H3：本地时间/赛后窗口边界的所有目标都有明确分类；覆盖统计分类之和=分母，unknown 不当成功，预算延期不漏计。
- H4：有可信赛时并已合法登记的赛事，T 状态推进在下一成功分钟任务完成；T+30 判 finished 不冒充 official。实时D0、已纳管、有预算且至少一条可用结果路线的来源正式结果首次可见到确认目标≤30分钟。late admission/date-only在D0为下一成功30分钟轮询窗口，D+1～D+7为下一成功6小时窗口加不超过5分钟入库处理；不是统一30分钟承诺。已观测但预算不足者明确budget_deferred，按实际延迟报告目标未达，不能从统计中删去；未观测到源首次可见时间则时效unknown。生产保留source首次可见与observed_at，不把计划开赛时间等同实际完赛时间。
- H5：旧 v1 fixture的准入和公开结果逐项不变，注册表加 unrelated route 后旧 digest/输出不漂移；新增全量测试失败=0（与同SHA基线比较）。
- H6：网络/内存/请求数不超过批准桶额度；20 event、每event至多2 source attempt的任务完整 accounting，任何未完成来源明确 deferred/failed。

以上为待实施验收，不是本轮测试结果。每个行为先 RED 后 GREEN；真实 provider响应使用脱敏固定 fixture，普通测试禁止联网和生产数据库。

## 回归清单

| ID | 场景与必须断言 |
| --- | --- |
| T01 | 104：TRA空、JRA唯一身份+13匹完整正式结果；独立登记、合法状态、一次结果publication；以source ID/key均无且series未审的冷启动A0 fixture验证，不是只对104硬编码；伪造URL/event_id、旧SHA缺失、错日期、链接跨域、旧baseline漂移均零写 |
| T02 | JRA/NAR/HK/UK/Ireland/France/US七桶至少一非TRA来源，无TRA身份也可登记；未配置地区零请求 |
| T03 | A→B、B→A、同轮；只补绑定，owner_generation与既有revision不重置；same provider双语页归一ID |
| T04 | オールカマー/All Comers/All Comer/中文名称；B强锚点一致自动同场，名称本身不当唯一键 |
| T05 | 同名不同日期/年度/场次、同日Division 1/2、JRA/NAR冲突；禁止合并 |
| T06 | active/过期/跨届次/无provenance别名、冠名变化、NFKC/简繁/标点；弱别名只能review候选 |
| T07 | A与B/C指向不同event、多canonical目标/环、source ID重用/同ID上下文冲突；整组拒绝 |
| T08 | UTC跨日/北京跨年/DST/官方延期；缺timezone、meeting_session或race_no时不伪造实例key |
| T09 | fuzzy、音译、翻译高分但无强证据；不登记、不改业务，最多5候选 |
| T10 | PostgreSQL两worker不同来源抢同一key；不同event整组冲突，同event幂等；savepoint重读、hash/payload碰撞、lifecycle缺行竞争及与现有lifecycle/rotation交错无死锁测试 |
| T11 | 一源empty/timeout/403/406，另一源成功；已登记A连续2次超时或403立即开circuit，B的合法完整赛果通过有期限授权接管；A恢复不抢回，超期alternate被拒绝；公平轮询，无TRA前置失败依赖，无绕过访问墙 |
| T12 | 身份/日期only可登记但空能力不派任务；race_time/card/result-only各只调支持能力，不能provider_not_implemented |
| T13 | T前、T后、T+5、D+1、D+7边界：未登记继续进入late admission；超窗保存incident；日期未知单列 |
| T14 | race_datetime=None的完整官方赛后结果仍可登记/完成；date-only polling不返回永不执行，也不造00:00时间；D0/次日分别按30分钟/6小时窗口，预算延期单列 |
| T15 | 首次result-only且runners=0：完整结果同事务bootstrap；中途异常全回滚，重试不重复；partial不建半名单 |
| T16 | 同着、退赛、未完赛、失格、coupled entry、缺行/重复马号；完整性守恒、来源finality未知不得标official |
| T17 | 两来源attach与登记/停用并发；单owner、单enrollment、source.event一致；更改binding集合旧claim失效 |
| T18 | 网络返回后claim过期/generation变化/人工锁/owner变manual；存observation但零投影 |
| T19 | route/terms/proof过期或撤销；隔离该binding，剩余合法binding可重算；不绕过统一admission；当前过期的旧有效publication仍可读，显式撤销/身份错误则隐藏 |
| T20 | 当前来源粘滞；后到高优先级不抢写；合法fallback receipt、恢复后选源粘滞、备用授权失效零写、更正标记、幂等不同源同内容不重复publication |
| T21 | 新v2 route加入，旧v1 policy/roster/identity及公开结果不变；不同版本不能混读digest |
| T22 | schema加表默认兼容；v1→v2 prepare/dry-run/apply中断、重跑、snapshot drift、源policy不可用均有确定恢复 |
| T23 | lifecycle/writer/public reader对相同准入合同给一致结论；无登记、锁定、契约漂移不各走一套 |
| T24 | T+5之后最后有效名单继续公开，带旧更新时间；新freshness缺失或赔率TTL到期不显示旧赔率 |
| T25 | 正式revision接管只显示一份；身份无效/人工锁/候选撤销后缓存同步失效；flag关闭行为确定 |
| T26 | 未登记也触发覆盖告警；D+1缺赛时、D+7后持久缺口，重复scan只一incident；停用不当resolved |
| T27 | 缺source、awaiting_window、manual_pause、budget_deferred、unsupported_region等统计守恒；matched不等于enrolled/confirmed |
| T28 | 同场跨语种runner slot/source ID对齐，不合并全球马匹；换号/替补/属性矛盾阻断结果覆盖 |
| T29 | 超时、超字节、分页中断、403、恶意/跨域URL、重定向、非UTF8及参数错误页均按来源合同拒绝 |
| T30 | 七地区高负载：20event上限、桶共享、512/day与1GiB预算含失败预留、公平轮转与下一批不饥饿；budget_deferred仍在时效分母且明确超标 |
| T31 | 0078发布合同+新迁移：旧进程排空、双版本读兼容、开关关闭无新写、v2最后有效公开版本保留 |
| T32 | 真实自然周期：来源实际新响应→identity→单登记→状态→完整结果→公网对照，连续两轮不重复写入，实时/late admission各按H4对应窗口验收，未知可见时间不算时效通过 |

## 执行

新增聚焦测试模块 `test_race_multisource_identity.py`、`test_race_multisource_enrollment.py`、`test_race_multisource_postgres.py`；parser用例扩展现有 `test_race_pre_race.py`、`test_pre_race_refresh.py` 与参考来源测试。沿用现有 lifecycle/control/results/admission 回归。SQLite验证纯函数/默认兼容，PG验证行锁/唯一约束/事务/迁移；不以SQLite替代并发证明。

实现阶段：`DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python server/manage.py test <聚焦模块>`、`python server/manage.py makemigrations --check --dry-run`、PG专用门禁、发布合同测试。全量 candidate/baseline stable 在 Linux CI 同run比较失败ID/类型/次数和SHA；本机不反复整仓测试。文档阶段仅验证链接、字段一致性、用例ID唯一及diff空白。
