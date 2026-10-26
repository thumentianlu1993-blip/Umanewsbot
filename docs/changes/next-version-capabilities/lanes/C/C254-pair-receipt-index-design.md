# C254：强关系 receipt 的私有 pair 历史索引

状态：DESIGN_ONLY / 待 ROOT→原 R_C 方案审。仅本设计与内含测试矩阵；未创建执行 runtime、产品模型/迁移/服务、测试源码或新的运行证据，未 commit/push。

依赖 HEAD `db6a246af8ec54779ce987f6c1d055d367d77e7f` / tree `a5b3671fe8b9b462c0b02e28b12598ec1705864c`。原 R_C253 report `d8e6e8b209245d2a344faa913fd03b98850a8943f2a91351ed7ca30b17d11576` / index `a089a6942634031ab58f4a6d24f4935b44b6d00ad396869b59562c175036f021` 已核对。20方法只读诊断的合成GREEN维持；正式 expired-skip FAIL、来源许可、全L02、durable/生产均不升级。

## 1. 复用边界与本次唯一目标

C249 第34–49、76–80行已确认：已知receipt PK/K/pair可以只读调查，但当前marker全擦除、关系缺行或无marker replacement时，scanner不能凭当前行发现历史。C250只修精确impact登记，没有解决历史发现。**不重写已经闭合的selected-receipt诊断，也不让它充当索引生产者。**

原L02（tasks.md:788–797 / design.md:771）要求更正与幂等传播，错误关系不自动复活。本片只设计一个可作为后续保护依据的、与真实新强写同事务留存的正向历史索引。自动防复活的生产启用、历史覆盖认证及回填仍未获授权。

推荐：**每个精确(article PK, profile PK)保留一份“首次入索引的强写receipt”不可变档案。** 不是“该pair历史上只有一次成功”，也不是“索引为空就从未成功”。只容纳首次受当前强writer准入的新created；不从旧log、marker、selected诊断或当前registry自动补录。

## 2. 当前源码事实

| 路径/行 | 已核事实及设计约束 |
|---|---|
| horse_article_binding_persistence.py:121–171 | `_admit`读取服务端handle/真实active staff/期限撤销/原件与用途；K来自canonical producer_namespace+request_id，不是pair的函数。默认配置不会被本片新增或授权 |
| 同文件349–400 | Article→Profile→Identity→当前pair锁；锁内再准入/CAS；原receipt按ACTION/TARGET/K读取。仅当前权威允许且决定成立的首次absent路径可能创建 |
| 同文件401–431 | link插入有内层savepoint；log在外层atomic内创建。receipt失败回滚link；created返回前是追加索引的唯一正常生产点。replay/历史缺行/漂移/保护/拒绝分支不补写 |
| models.py:4170–4208 | 当前link唯一pair，article/profile级联删除link；不能将历史索引FK到可删除link或依靠其marker长期保留 |
| models.py:5770–5789 / admin.py:1738–1743 | OperationLog.detail为普通TextField、admin FK为SET_NULL；该admin类仅readonly字段，未定义本类的禁止删除策略。定向搜索未找到horse_binding_request专用保留/归档合同；不能假设永不删改 |
| C253已采信的真实admin删除用例 | User删除使log.admin_id变NULL，旧canonical detail.actor_id不改。selected诊断按当前log返回invalid是原合同，不得为新索引改变这20项oracle |
| horse_profiles.py:499–551 /618–640 | 两个弱writer使用父Article→关系锁；profile分支的get_or_create发生在现存marker保护前。历史guard必须在它之前，否则已缺行的pair会先被创建 |
| migrations/0069…ledger_guards.py | 本仓库已有PG BEFORE UPDATE/DELETE拒改的append-only表模板。它不独立解决TRUNCATE、DROP、owner禁trigger或同DB凭据伪造INSERT |

没有查生产DB、现行DB角色/ACL、运维purge或外部许可。上述是固定源码事实；索引的实际保留/安全能力不得由代码静态检查冒充上线验证。

## 3. 方案选择与权威含义

只给OperationLog加pair字段/指针而不留原件，会受删log、SET_NULL及文本改写影响；仅按K建索引仍不能精准pair发现。多receipt-per-pair追加表还需多K胜出/释放/版本裁决，当前合同未提供，不作为首片。

选一张私有不可变档案表，保留精确原receipt原字节、校验摘要与历史身份。其“权威”限定为：**现有已审服务端准入域的真实writer在同一提交中形成并保全的事实**；不从一份自洽JSON或SHA自行认证来源/许可。DB保护防一般更新/删除；不能声称对DB owner、迁移权限或同凭据任意SQL不可伪造。第10节列出ROOT必须裁定的信任边界。

表不注册Django admin，不新增HTTP/CLI、settings注册入口或通用“导入receipt建立索引”API。唯一应用INSERT调用点为原strong writer的created尾部；不提供自由DTO/trusted=True/authority_verified参数。内部私有调用仍受现有服务端进程/DB凭据信任边界约束，private命名本身不是安全隔离。

## 4. 最小数据合同（拟议，尚未建表）

拟模型 `HorseArticlePairReceiptIndex`，普通Model，不继承会自动更新updated_at的基类。

| 字段 | 来源/约束 |
|---|---|
| id | 新表自己的BigAutoField，仅档案标识 |
| article_id_snapshot / profile_id_snapshot | 实际锁后Article/Profile PK，正整数、**普通BigInteger字段，不是FK**；组成唯一pair |
| producer_namespace / request_id / request_key | 锁内重新准入得到的scope；K沿原`l01.horse-link-request.v1` canonical公式计算并与receipt/metadata交叉核对；K全表唯一 |
| operation_log_id_snapshot | 同事务实际新建log PK，正整数、非FK、唯一；不是可自由选择的历史log ID |
| original_link_id / original_actor_id | 同事务真实link PK及锁内真实current_actor PK；正整数非FK，保持历史值，不随User/Link删除SET_NULL |
| receipt_detail / receipt_detail_sha256 | **实际log.detail的完整UTF-8字节**及SHA-256，不从当前marker重建，不只存重新序列化的JSON；原件须canonical且≤既有4MiB读取上限，超限整笔新写失败 |
| protocol_version / recorded_at | 固定私有schema与事务内服务器时间，仅说明捕获协议/时点，不充当历史覆盖cutover证明 |

DB唯一约束：`uq_horse_pair_receipt_pair`(article_id_snapshot,profile_id_snapshot)、`uq_horse_pair_receipt_key`(request_key)、`uq_horse_pair_receipt_log`(operation_log_id_snapshot)。pair唯一约束本身提供精确查找索引；不另加无用重复索引。正ID/hash形状/原件字节上限可用表约束；canonical、after字段全绑定和摘要由既有纯校验原语及只读reader重验，不引入hash扩展或新的许可机制。

这是“第一份已入索引的receipt”，不是全历史唯一。不同K申请同pair的新自动占用、同K跨pair或同log映射多个pair均冲突关闭；不允许覆盖、upsert、last_seen更新、换PK重绑定或“最新一条胜出”。将来确需多版本/释放，必须独立合同和独立审计，不能改变此历史行。

## 5. 原子捕获、重试与锁序

1. 完整保留原writer准入/再准入、身份、snapshot/CAS、decision及current人工优先，不安装真实handle或来源许可。缺当前authority依旧零关系/log/index写；fixture只留在隔离合成DB，不迁往生产。
2. 原Article→Profile→Identity→pair顺序不倒置。将要走首次created路径时，在同一父Article锁内精确读pair索引与request-key唯一映射；任一既存冲突/坏档案拒绝新写。索引不可变，无需新增索引行锁或先锁索引再等Article。
3. 原真实link创建→实际log创建→按新log PK重读并核ACTION/TARGET/K/admin及canonical data一致→冻结原字节/身份/摘要→索引INSERT→外层提交，全部在同一连接的同一atomic范围。不存在先提交log再异步补索引。原件超限、结构错误、索引schema/DB故障都必须回滚新link/log/index，不能悄悄退回旧created成功。
4. DB唯一约束承担不同Article并发复用K的最终防线。只对明确命名的索引唯一冲突，在**包含本次link/log/index全部写入的atomic/savepoint已完整回滚后**映射原`history_conflict`；其他IntegrityError、OperationalError、超时/驱动错误原样上抛。不得在已坏事务中查询恢复或提交孤儿log。没有重试新K、重签原件或更新赢家行。
5. 原replayed/protected/historical_missing/drifted等零写分支不自动补索引；有索引时仍需原writer当前authority才能replay。历史旧receipt无索引继续是覆盖UNKNOWN，不能因为一次当前调用就倒签其捕获时点。零写的既有返回语义无需为了“补齐”改写。

仅当前真实新写准入允许捕获，不把“索引缺失”当成新许可。第一次捕获只能说明此次新提交已留档；可能存在更早其他K的未索引历史，表不能声称将其抹除或已查清。若ROOT要求首次捕获还须证明该pair从无更早历史，当前合同做不到，必须先取得第10节的独立覆盖权威，不能造negative行补洞。

## 6. 删除与保留

- 对新表以已有PG模式拒绝UPDATE/DELETE（包括同值UPDATE和QuerySet/raw SQL），不只覆盖Model.save/delete。全部字段都不可变，没有可变live FK；因此User/Log/Link/Article/Profile删除不会级联改档案。
- User删除：旧log.admin照旧SET_NULL，档案original_actor_id及原detail保持。**不改C253诊断**；新的pair-reader只核捕获时的历史身份，不重新要求旧actor仍存在/active来决定历史是否消失。
- Log删除/改detail：原log不再是索引运行时的唯一存储根。reader用保全原件；不因live log缺失而删档案、重新取值或降成普通pair。给定明确log选择器的人工调查可以另报live-log-missing/drift，但scanner不回查log。
- 关系缺行/replacement/父实体删除：档案充当正向历史保留，绝不恢复实体或旧PK。不自动迁移到合并后的新profile/Article；ID人工复用不能获得自动释放。
- 最小方案不设TTL或自动purge；归档须保留原字节和可查询pair键，离线移走导致不可查询时按UNKNOWN关闭。法定擦除/真实保留期限没有现成授权，ROOT须先定政策；本设计不替用户批准永久生产留存。
- TRUNCATE/DROP/owner禁trigger不在普通行trigger保证内。生产runtime角色必须无这些权限/DDL所有权，owner维护为显式break-glass；若无法验证，不能认证生产immutable或覆盖能力。不要为绕开测试flush设计application_name/test=True豁免。隔离测试owner的TRUNCATE清库是测试基础设施边界，不是产品授予的删除接口。

## 7. 精准pair只读分类与UNKNOWN

拟内部reader `classify_pair_receipt_history(article_id, profile_id)`：仅精确双键查询新表、最多2行，校验schema/原字节SHA/canonical/完整after/历史身份/K/pair绑定；不取当前registry，不搜任何OperationLog、不查名称、不修补索引。返回**是否必须停止弱变更的原因**，不是许可或replay结果。

| 状态 | 已知事实 | 弱变更决策（仅未来获准enforce域） |
|---|---|---|
| INDEXED_HISTORY | 唯一可信捕获档案及存储绑定成立 | 此pair的create/update/delete全部停止；与current marker/PK是否存在无关 |
| UNKNOWN_NO_INDEX | 精确pair未读到索引；无法区分never-strong与旧强历史 | 停止，不返回LEGACY_MUTABLE/允许创建 |
| UNKNOWN_LEGACY_UNINDEXED（调查标签） | 人工已给明确旧receipt选择器，已知旧log但无索引 | 仍停止；该事实只能来自显式调查，pair-only reader单独无法作此区分，不加log搜索来凑标签 |
| UNKNOWN_CORRUPT_OR_UNSUPPORTED | 档案schema/hash/原件/身份/K/pair不符或超限 | 停止，不改after/hash、不找另一个log补成合法 |
| UNKNOWN_CONFLICT | 多行/唯一约束失效或显式身份冲突 | 停止；不取最新/任意一条 |
| 技术查询失败/表或权限缺失 | 无可用观察；不是历史不存在 | 异常上抛、该次弱变更不得继续；不吞成no-index或成功 |

缺live log、旧actor被删、current scope过期与“档案原字节坏了”不同：前两者不自动破坏已捕获档案；后者是UNKNOWN。原件自洽也不认证来源/公开许可/当前权威。不返回一个“索引存在所以允许强重放/重建”的成功分支。

**没有覆盖权威时，缺索引不能给弱写放行。** 所以该reader若全局接入会冻结很多无法证明历史的普通pair。首片只能“新created原子捕获+私有只读分类”，不在本卡或下一捕获源码卡启用scanner自动保护；不按空表、日期、article.created_at、数据库sequence或当前registry伪造历史覆盖。真正启用必须另获精确作用域与coverage依据，不能依靠默认开关为true。

## 8. 后续scanner接缝（本卡不实现、不启用）

未来另卡获准后：保留当前MANUAL/REMOVED优先；父Article锁后，对create/update/delete涉及的显式pair逐一调用reader。profile/global必须在get_or_create之前查；reconcile取desired与现存/原计划profile IDs的有限并集，每次索引查询都带精确双键，不查整篇Article所有历史索引或全部log。当前WITHDRAWN合同不变，不借此补profile撤回语义。

所有UNKNOWN与INDEXED_HISTORY均零弱DML；当前marker全擦除、当前关系已删或换PK也不例外。preview只能表达同一观察，commit仍在锁后重读，不能把旧preview作为许可。不得捏造缺行的link_id塞进protected_ids；保留旧结果shape/计数，阻断原因由私有reader提供，若要新增public计数/字段须另定合同。默认现有scanner不被改动/启用，D模板和公开reader不在责任内。

## 9. 最小分片与具体文件责任

| 后续片 | 拟文件 | 唯一责任 |
|---|---|---|
| 首片：schema+capture+read，先测试后实现 | server/stable/models.py | 只新增私有档案模型/约束，不改OperationLog/User/旧Link字段 |
| 同片 | server/stable/migrations/0082_horse_article_pair_receipt_index.py（待ROOT锁号） | 基于0081追加schema/行不可变guard；无RunPython回填、授权注册或生产执行。若其他线已占0082，交ROOT定新号/依赖，绝不覆盖 |
| 同片 | server/stable/services/horse_article_pair_receipt_index.py（拟新） | 私有捕获校验及精确pair reader；不提供历史导入/自动补账/许可API |
| 同片 | server/stable/services/horse_article_binding_persistence.py | 唯一created路径同事务捕获、精确冲突关闭；原准入、CAS、旧零写语义不放宽 |
| 同片测试 | server/stable/test_horse_article_pair_receipt_index.py（拟新） | 下列真实PG矩阵；不改原20/15/17/13 oracle |
| 精确登记 | tools/test_impact/catalog.json / rules.json | 现content_contracts加新test label/file/profile；新service精确路径→同一entry，保留unknown failclosed，不加域/通配/fallback |
| 后续独立启用片，当前不授权 | server/stable/services/horse_profiles.py | 仅在已批准作用域父锁后、DML之前精准pair guard；不可混入首片悄悄生效 |

不改当前diagnostics/coordinator/tasks/views/admin/public模板/settings权限/model其他字段；不创建outbox、negative registry、全局扫描器或来源grant。迁移号、部署角色、保留与coverage认证不由实现者擅定。

### 拟测试矩阵（尚无源码或执行结果）

首片测试schema/capture/reader与原回归；涉及真实弱scanner的DML阻断、preview/commit及作用域启用测试属于后续独立集成片，不在首片偷偷接线。

| 场景/要捕获的错误 | 真实前件与主要oracle |
|---|---|
| 正常原子三件套 | 独立PG真实staff/server-owned合成包经原writer created；实际link/log/index唯一，raw bytes/UTF8 SHA/pair/K/ns/request/actor/PK逐项独立绑定；不mock成功 |
| 捕获点各阶段失败 | 真SQL故障/约束拒绝分别发生于link、log、index；提交后三者均不留下本次部分成功；其他技术异常不换成“无历史” |
| 权威/CAS拒绝 | 真实过期/撤销/actor失效/输入变化，三表零新增；索引/自洽JSON不提供许可 |
| 精确重复 | 同handle/alias重放，所有原件/档案全字段和数量不变，不更新时间或补档 |
| 同pair不同K与同K跨pair | 有current row时保留原existing_pair_conflict；缺row但pair已入索引时history_conflict、零三表新写。同K跨pair先核原_admit的peer冲突拒绝；另以首份真实captured、旧log已删、真实新scope重用K验证永久阻断。DB唯一竞争用明确负向fixture/实际连接验证，不能mock两次_admit成功或将无法成立的前件冒作业务RED |
| marker擦除/缺行/replacement | 从真实created档案出发，明确fixture改当前行；reader仍INDEXED_HISTORY、无业务写；普通/人工新PK不覆盖original PK |
| 真实staff操作 | confirm/remove/reset及人工删除后档案原字节不变；reset不是release；不自动恢复旧row |
| User/log/父实体删除 | 真实admin SET_NULL、log删除/改文、Link/Article/Profile删除，档案不级联变化；C253 selected诊断原结果不改 |
| 缺索引/已知旧receipt | 无记录只报UNKNOWN；已给旧PK可标legacy-unindexed，但不回填/不扫log/不推断历史为空 |
| 坏档案/冲突 | 通过明确隔离DB-owner fixture准备坏raw/hash/schema/pair或破坏约束，不mock reader；全为UNKNOWN、不修复。准备错误单列，不算业务RED |
| 数据库不可变 | 在受测runtime连接实际UPDATE/DELETE（含同值UPDATE/QuerySet/raw SQL）均拒绝，原字节/数量不变；DDL/TRUNCATE权限单独用隔离角色验证，不伪称owner也被行trigger约束 |
| 捕获与弱writer两种顺序 | 实际父Article锁协议：先强提交则后读命中；先弱读无索引为UNKNOWN不写，随后强自然提交；调度不冒称PGblocking证据 |
| 技术失败与预算 | 真driver/timeout/缺table/权限错误上抛，不返回MISSING或LEGACY_MUTABLE；线程、SQL与资源清理有界 |
| 原回归及启用边界 | 原20/15/17/13、保护5/3/withdrawal2及full native回归；首片不接scanner，不声称自动保护启用；新增方法数量由后续源卡冻结 |

所有正向档案来自真实writer的新提交；历史回填、生产导入或将synthetic档案变成真实许可均不是fixture捷径。没有DB执行资格之前不得跑矩阵、造RED或把未运行结果写GREEN。

## 10. 请ROOT在方案审直接裁定的未决点

1. **第一份入索引占用是否永久保留。** 推荐本片只允许一pair一档案、不同K冲突关闭；原合同没有释放/多版本裁决。若要求重绑/删除后重新授权，要另定版本与release，不能在本片猜测。
2. **权威信任边界。** 推荐沿现有server-owned准入域、真实writer原子捕获，DB拒改配合生产runtime最小权限。若要求DB独立识别“此INSERT必由经过_admit的调用”，现有权限仅在Python/settings/文件中，DB没有该事实；需要另定DB角色/受审入口或凭据协议。不能拿private命名、SHA、application_name或可设置session变量替代。
3. **无索引时的启用范围与覆盖。** 推荐缺失永远UNKNOWN，首片record-only/read-only，不全局冻结现有普通scanner，也不把它继续写解释为已受新保护。启用前必须另有明确coverage/cutover/历史处理决策；现有log、时钟与registry无法证明旧历史已完整入索引。
4. **生产保留/角色/迁移所有权。** 推荐无自动TTL、历史标识非FK；真实保留与擦除政策、runtime能否禁用trigger/TRUNCATE/DROP、0082是否与他线冲突都未从源码确定。未解决时只准隔离机制开发，不认证生产immutable、不运行迁移/回填或启用。

这些是具体约束，ROOT可直接选择；本卡不要求用户机械确认。后续部署若回滚代码到不捕获版本，新增期间的覆盖必须重新标UNKNOWN，不删除旧档案；任何生产迁移、停旧worker/切换、保留/归档/历史回填及自动enforce均须另一个精确授权包，不从本设计推导。

## 固定依赖指纹与本卡核对

| 源文件 | SHA256 |
|---|---|
| models.py | 5c11bca5f55dfffab0fa4720a565b0b58fbde688f930a9a4fab2d8aabe942749 |
| admin.py | 9e44fe151de897af3051977fd460928ab574b5228e20bf21e7b6e88df76df2b8 |
| horse_article_binding_persistence.py | 71f6d20b013be41f171a31e918f8fcad870d9834979c742d887b59d08efdfa01 |
| horse_article_binding_diagnostics.py | 4879a941a4a09497d032bd9611589fd01720b6d39662e30cde400136427e8e4b |
| horse_profiles.py | 18545b3e4e7858790635e3846a7f5c0477726f630d4894709c763eff519df011 |
| horse_article_strong_backfill.py | b144f651862e2d4353a2f35fa9a1f94d838e2387f577dc684fb5499cd64d9fb8 |
| migrations/0069_race_data_sync_pipeline_a_ledger_guards.py | a419b065cb16497d539642a83e5aac356f8c90233c3b798b3a78c45794205246 |
| migrations/0081_managed_readonly_steps.py | cacddeb755a92be63e7b4b74a7df716d6af11b3dd46d2a762fbb6d24b221b06b |
| catalog.json | fb7589c43411f473bebfdfa48eb909469d4700dca77bf7f1508f54fdb01853e9 |
| rules.json | 02c7af86571b4ecf4d269b23868b9625972d1bf67188c873a79c194f3e89a86c |

仅Git/源码/既有封包读取与文本/引用/哈希核对；设计没有新运行结论。后续同原R_C先审方案，再由ROOT给测试/实现源卡。此文之外不写产品代码、模型、迁移、测试或执行runtime；不触D模板、不commit/push、不DB/CI/生产操作。
