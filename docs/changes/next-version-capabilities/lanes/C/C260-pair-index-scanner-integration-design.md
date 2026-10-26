# C260：pair receipt 历史索引接入既有弱扫描器的最小设计

状态：DESIGN_ONLY / C261单P2修订，待 ROOT→同一原 R_C 仅复审事务快照finding。原设计SHA `4ca6c99f944dd019c855a2a5d7dbb6dd76c0e13080d10a6ed3dc9c957e746dae`，原审report SHA `4c4fd1eac98c91758664601325ea02b5656a2c9ad9821cf5c0528b95ee8be1a3`；仅明确RC可写准入、对应负控和原始输入预算口径，其余C260策略不变。仅此文；不实现、不建测试源码/执行 runtime，不 commit/push、不测试/DB/CI/迁移。基线 HEAD `c714385545a5f963f917ac5bd34514eddcd9df63` / tree `8a61fbdf5ef5ead2cabdb935509f502fd193e606`。

C259 固定合成27、旧20/15/17/13及原116方法已获原R_C接受；正式 expired-skip gate仍FAIL，pre-RED NOT_RUN、独立collect/image未验、外部CID清理UNKNOWN。原C25726P1F/full117负方法及原件保留。本设计无新运行结论，不称整L02完成。

## 1. ROOT本卡补充裁定与唯一方案

采用**新增确定性索引保护，原policy继续独立负责未命中者**。不增加enforce开关、迁移、历史导入、回填、来源授权或生产启用。以下裁定明确替代把C254未来全UNKNOWN拒写域机械套用到当前所有scanner的做法：

| reader实际观察 | 本片新增保护决定 | 含义 |
|---|---|---|
| INDEXED_HISTORY | 阻断该pair全部弱create/update/delete | server-owned强writer同事务捕获的首次档案；不依赖当前marker、link PK或当前K |
| UNKNOWN_NO_INDEX | **无新增索引保护命中**，仅在实际READ COMMITTED可写前提已核实后继续原policy | 未知，不证明never-strong、不把weak_mutation_allowed改true，也不新增权限；未索引历史仍可能被原路径改动，coverage/cutover未解决 |
| UNKNOWN_CORRUPT_OR_UNSUPPORTED / UNKNOWN_CONFLICT | 候选未知保护，该pair零弱DML，不修复 | 不能降为NO_INDEX或退回普通弱写 |
| 数据库/权限/超时异常 | 原异常抛出，当前事务不继续弱DML | 候选是否存在都未能可靠观察时，也不能假造absence |
| reader DTO畸形、pair不符、未知schema/state/恒边界或引用字段不一致 | 稳定内部合同错误，当前事务fail closed | 不以宽泛except返回普通pair |

同一实际调用中，已索引/坏候选pair受保护，另一无index普通pair继续满足原matching/发布/人工保护规则才可原样写入。不能用“返回NO_INDEX”替代那些规则。此方案无需新许可状态；reader固定17键/四态/weak_mutation_allowed=false不改。全缺失一律拒写会违背本卡裁定和既有普通pair合同；只看live marker则无法覆盖缺行/擦除；故不另开方案循环。

## 2. 已就绪的真实调用路径

| 真实入口 | 当前落点与事实 | 本片接缝 |
|---|---|---|
| 发布/重发链 tasks.py:2306、2452、3083 | dispatch scan_article_horse_links_task(article_id=…,commit=True) | 不改生产dispatch；同一任务函数1209–1218进入下述article分支 |
| scan_article_horse_links(article=…,profile=None):556–581 | resolver→reconcile_article_horse_links:413；完成后写一条扫描TaskExecutionLog | 在reconcile中统一保护create/update/delete，不在任务外围重复造guard |
| staff profile扫描 views.py:1081–1090；任务profile_id；management/commands/scan_article_horse_links.py | scan_article_horse_links的profile/global分支:582–645；当前逐pair Article锁→get_or_create→现存保护 | 改为先锁读现存pair，再保护/历史观察，最后才进入原get_or_create/更新 |
| CLI reprocess_article_entities→article_entity_reprocessing._commit_article:95–184 | 外层atomic已锁Article，保存tags/metadata后调用reconcile；成功写reprocess OperationLog | 共享reconcile接缝，不增第三个writer；技术异常向外传播使该article事务回滚 |
| build_article_entity_reprocess_plan:67–84 / reconcile(commit=False) | 真实dry-run计划 | 相同历史分类过滤计划；preview不是后续commit许可 |
| profile/global commit=False | 当前仅统计匹配、无关系DML；candidate是命中数 | 只作同一观察，不改旧计数定义/公开shape，不声称preview可授权 |

当前reader `horse_article_pair_receipt_index.classify_pair_receipt_history(article_id,profile_id)` 已在C259真实PG验证，可在原事务内调用；不要求独立顶层事务，不查live log/actor/registry，无写或行锁。现有状态足以区分NO_INDEX与坏/冲突候选，**没有需要先补模型/API的阻塞，不新增record-only重复slice**。

## 3. 最小文件/函数责任

1. `server/stable/services/horse_profiles.py`：仅新增私有history观察/DTO检查/事务内预算辅助，接入`reconcile_article_horse_links`和`scan_article_horse_links`的profile/global分支。现`_article_horse_link_protection`的manual/removed/marked职责不重写；新helper不能接受调用方传入的trusted/observed DTO或K来绕过实际reader。
2. 拟 `server/stable/test_horse_article_pair_index_scanner_protection.py`：一个独立TransactionTestCase，通过模块引用组合现有strong测试`_Domain`的真实producer、weak_precondition/invoke，以及C255/C258的真实归档/owner负控/完整锁SQL观察方式；不继承或导出旧TestCase，不复制核心writer/reader/resolver，不增孤立demo或假服务。
3. `tools/test_impact/catalog.json`：只追加新test的content_contracts label、file登记和django profile。`horse_profiles.py`目前已属high_risk、reader已有content_contracts精确映射，**无需新增rules域/通配/fallback或改高风险策略**；后续源卡复核精确登记即可。

不改27机制oracle、旧20/15/17/13、model/0082/强writer/私有reader协议、article_entity_reprocessing业务内容、tasks/views/CLI返回协议或D模板。若后续证据确需改这些边界，先报具体缺口，不悄扩。

## 4. 事务、优先级与动作集合

### article/reconcile

保留现有plan构造。commit在原atomic内锁当前Article，再以现有`.order_by("id")`锁当前关系；保留WITHDRAWN返回和manual/removed/marked保护。**在任何delete/create/update之前**，形成desired profile IDs、初读existing/旧计划 IDs、当前锁定关系profile IDs的有限并集；过滤无任何待执行动作的pair，按profile ID固定顺序观察其余pair。绝不查整篇Article的所有Index或搜OperationLog来发现历史。

对已被旧保护覆盖的当前行不再要求index授权。对其余动作pair调用真实reader：确定性命中及坏/冲突候选均从三个DML计划中排除；NO_INDEX保留给原policy继续判断。预先分类全部动作pair再开始DML，避免后一个reader技术失败发生在前一个delete之后。当前原子块异常整体退出，不在坏事务内恢复查询/吞错。

`current_links`按旧PK/原profile核对的CAS约束、当前`current_by_profile`及原mutable_statuses均保留。缺失行从desired/旧动作pair发现；换新PK只用实际当前行标识，不拿receipt.original_link_id冒充现存行。当前无marker也无行时，首次档案仍按精确pair命中。

### profile/global

保留真实matcher与初读的advisory性质；每pair仍是原来的独立atomic单位。锁当前Article后，以精确pair锁读当前关系，显式PK排序避免默认关系排序引入额外JOIN；检查manual/removed，再检查原marked保护，然后实际history观察。**此时不得已经调用get_or_create、INSERT或save。**

history阻断即跳过该pair，继续下一普通pair；NO_INDEX才回到原有独立policy，并在同一Article锁内执行原get_or_create/更新逻辑。不是新增NO_INDEX许可，也不把一次观察缓存成跨调用token。旧初读MANUAL/REMOVED优先及锁内复核不削弱；不借本片增加Profile/Identity/Index行锁或修改强writer锁序。

两个弱路径均维持Article→当前Link的合作锁顺序，强writer仍Article→Profile→Identity→Link；相同Article父锁只串行化合作调用，**不刷新RR/SERIALIZABLE的既有snapshot**。索引不可变，不对Index加FOR UPDATE；Article只被锁而未更新时，不保证会报40001，旧快照看不到新Index也绝不能获得普通弱写回退。

**可写事务准入（C261 F1）**：`reconcile(commit=True)`及profile/global每个实际atomic写入单位，在父/当前Link锁及旧零DML保护判定后、任何新增history观察、NO_INDEX回原policy以及weak get_or_create/INSERT/delete/update/save之前，必须通过原QuerySet/atomic的`using`别名绑定的**同一实际连接、当前事务**执行`SHOW transaction_isolation`，同时确认该连接正在原atomic内。只接受实际返回`read committed`；RR、SERIALIZABLE、其他级别、无法确认/合同返回畸形均以稳定内部`PairHistoryTransactionError`、代码`pair_history_requires_read_committed`拒绝，不进行弱DML。不得凭settings默认值、driver的default属性、输入对象或“新进了一个atomic”推断RC，也不能仅当Index候选已知存在才检查——旧快照恰可能把候选藏成NO_INDEX。若不能确认这正是待写ORM与现reader共用的连接/事务，同样按事务合同错误退出，不拿另一个alias/default连接的SHOW替当前写连接背书，不扩多库或新API。SHOW自身的真实数据库/权限/驱动错误原样上抛，不改成业务absence。

检查放在两条真实scanner内部，每个可能进入弱写的事务单位独立执行，不能只在task/CLI入口检查。`article_entity_reprocessing._commit_article`已有外层atomic、`reconcile`在其中只是savepoint，必须查询同一backend的实际RR/SERIALIZABLE状态并拒绝；不新建连接逃离外层快照。已经由WITHDRAWN/当前manual/removed/marked完整排除全部弱动作的路径可原样零DML返回，不为此增加许可或改原保护结果。锁阶段若先发生真实driver/serialization错误，保留首因并退出，不伪装已取得上述稳定准入错误。

运行时guard不得SET TRANSACTION/SET SESSION/global isolation、重开连接、重试或重启事务来“修好”输入。只有实际RC准入通过后，NO_INDEX才交原policy；这不是全无索引拒写，也不改变RC普通pair的既有行为。只读pair reader与preview仍可观察RR snapshot、原样返回其观察，不能把该NO_INDEX用于commit许可；C253只读诊断自有RR合同也不改。owner/同凭据任意SQL不受这套合作协议独立防伪。

保护优先级：原WITHDRAWN（article分支现合同）→当前MANUAL/REMOVED→当前marked（含原strong_unknown）→新pair历史保护→原弱匹配/普通写policy。profile分支未独立补齐的撤回语义不在本片冒领。不同K不能释放已索引pair；不按当前scope/metadata K筛掉首次K，不覆盖/续期/补历史，无TTL/释放版本。

## 5. 返回、零写与异常边界

- 保持reconcile现有create/update/delete_ids/protected_ids/protected与scanner计数字段。当前确有行时可在原protected中用**真实当前link.id**加内部reason（如indexed_pair_history或pair_history_unknown）；缺行只排除create，不伪造protected_ids或把历史link PK塞入列表。
- history观察及阻断不新增OperationLog/TaskExecutionLog，不修marker/档案/原件。正常scan现有一条成功TaskExecutionLog照旧，candidate仍为匹配数，不能把它当新增关系数；不新增公开blocked计数或D模板口径。缺行原因由私有reader观察与测试原件解释，不伪装已有保护行。
- 直接reconcile在全部动作被挡时可断言全DML零；任务入口则断言关系/strong日志/Index/authority/producer零变更，另外单列现有扫描审计。显式reprocess正常阻断关系后仍可能保存tags/metadata和原成功审计，不能称整调用全表零写。
- 可写事务准入及reader技术/协议/预算错误：reconcile当前article事务回滚；若在reprocess外层，tags/metadata成功日志也回滚，但`reprocess_article_entities`已有外层catch会另写`article_entities_reprocess_failed`，必须单列真实失败审计。profile/global是逐pair事务，错误pair零写并外抛；此前已完成的其他pair不假称全任务回滚。不能吞错误继续普通弱写或输出虚假成功计数。
- preview不建索引、不改配置/许可/原件。article preview用相同相关pair集合过滤计划；profile preview只观察，无新公开shape。commit必须重新锁/重读，不能复用preview命中或NO_INDEX缓存。

## 6. 新增观察的有限预算（实现前由方案审冻结）

建议每个article事务最多16个需history观察的不同pair，profile事务只有一个pair；同事务同pair只读一次，跨事务/preview不缓存。每次reader最多两行header、合法原件最多4MiB；新增data SELECT上界32、16份原始UTF8 receipt输入累计上界64MiB，不同时保留所有原始输入；**64MiB不是JSON对象堆、重复canonical编码/复制的总分配量或整个Python进程的硬内存上限**。超过pair预算在DML前报预算错误，不能截断集合后把未观察动作继续执行。

建议在scanner原atomic/savepoint内、父Article和当前Link锁已取后，仅对新增history读阶段临时使用statement/lock timeout上界2秒（不得放宽调用方更严格值），正常退出恢复原GUC，异常由savepoint/外层回滚恢复，不在坏事务finally另发SQL掩盖首因；实际事务隔离级别SHOW与额外timeout SHOW/SET/restore、savepoint语句均是固定开销，和32条reader data SELECT分开计。新增guard阶段elapsed预算5秒，在每次读前/读后和DML前核对；已在执行的Python解析不声称硬抢占，仍受4MiB/条和16pair上界约束。

这只约束新增history观察（包括其DDL锁等待），不追溯或另行改写之前的父/Link锁等待预算，也不谎称现有resolver/翻译或global全部profiles×articles已整体有界。global现limit只约束文章数、profile数未限；本片不借此做新调度/分片项目。已在上层reprocess取得的父锁/翻译耗时也不被scanner内部timeout追溯约束。真实双PG测试沿用SQL10秒/lock5秒、barrier5秒、总30秒和有界join/cancel，记录实际GUC及清理；正式预算值随原R_C方案审冻结，当前不执行或调时钟。

## 7. 真实测试接缝与首次RED判定

真实数据复用现`_Domain`：实际staff、owner只读bundle、真实admitted writer产生link/log/Index，再用真实ORM作明确负向marker擦除/删除/ordinary新PK准备；不手写正向Index receipt、不mock成功resolver/reader/ORM/_admit。`weak_precondition`必须验证真实matcher/resolver确实提出目标update/create/delete；先保存准备后的当前行及原日志/Index/配置/原件，再调用真实task/CLI/reconcile。新测试只依赖现有task/scanner/reader，不在setUp导入或等待拟新增guard/helper/class，避免把缺集成变成NOT_READY遮蔽真正业务RED。

| 矩阵 | 真实调用与断言；当前基线可能产生的有效RED |
|---|---|
| 擦除marker | article/profile真实任务；原索引存在，当前source/metadata已擦，旧路径实际update，新增保护应完整保留准备后的当前行，而非从档案“修复” |
| 当前行删除 | 先真实强capture再真实删Link；两个任务因实际匹配会create，修后created=0、无新PK、日志/Index不变 |
| ordinary replacement新PK | 明确隔离负向ORM准备新当前PK；article update/delete及profile update均应保护新当前行；protected_ids不得历史PK冒充当前PK |
| resolver无目标delete | 真实reconcile/article任务无horse desired，旧路径会delete已擦marker当前行，修后delete_ids空，当前/历史字节不变 |
| 优先级与混合普通pair | 原manual/removed/marked保持优先；同一调用中新增命中pair零DML，另一个真实NO_INDEX普通pair仍按原policy更新AUTO95/创建/删除；旧15普通合同保留，不全局冻结 |
| 同pair不同K | 先真实K1 capture，后同pair真实K2准入请求按原强writer返回existing_pair_conflict/history_conflict且不换档；弱扫描不按K2或失效当前registry漏掉K1历史；不伪造两个准入成功 |
| 坏/冲突候选 | 复用已审owner负控，真实捕获后才破坏Index/check/unique，finally完整恢复；真实reader应返回候选UNKNOWN，不能退回普通写或修原件 |
| 技术异常/协议/预算 | 真SQL22012/缺表42P01/timeout57014在Index SELECT边界注入并原样上抛；记录实际到达、SQLSTATE和单位回滚。协议检查与真实>预算动作集不作为权限grant；预算截断不得导致剩余动作写入 |
| preview→commit | 真实preview无写；之后真实强capture/删行或人工动作自然提交，再commit必须锁后重读历史和当前状态，不能复用旧preview许可 |
| 两种真实RC PG顺序 | 保留下一节两个原RC窗口及普通NO_INDEX控制，记录实际read committed；使用现有Article FOR UPDATE作为barrier，不等待尚未实现的reader seam而把缺集成制造成NOT_READY |
| 已建旧快照的RR负控 | 同一真实外层RR先由普通SELECT固定旧snapshot，另一真实writer随后capture/负向删Link并自然提交；实际父锁等待后，可写scanner应稳定拒绝且关系零DML，详见下节。不要求PG必报40001，不mock NO_INDEX或导入未来guard作setUp前件 |

畸形DTO的防御分支先按固定schema/源码合同核对，不mock真实reader伪造该分支作为PG RED或driver证据；坏档案用owner负控取得真实UNKNOWN，技术错误用实际SQL取得，不冒尚未动态覆盖的合同分支。矩阵行/循环不等同native方法数，后续测试源卡明确枚举。API/物理schema/权限/线程等前件缺失单列scenario ERROR；只有实际weak调用造成非法行变化或应抛异常却继续写才是本片业务FAIL。原15的`_LateStrongWindow`明确只有调度等待，不搬作PGblocking原件；C259真实capture窗口也不冒本片scanner窗口。当前不运行，因此不预报RED/GREEN。

## 8. 双PG真实零弱写oracle

**A先持锁并提交新索引。** A在真实外层atomic里调用正常strong writer完成实际三件套，随后仅作显式负向删Link准备，保留原Index并持Article锁，暂不提交；B启动真实scanner（初读absent/真实desired将create），观察B实际Article FOR UPDATE尝试。独立观察连接采样pg_blocking_pids(B)包含A；不让A等B持锁后才提交。释放A自然提交，再B锁后读取Index并零create。当前无集成代码会真实复活Link，形成行/PK/计数业务断言FAIL，不以等不到新reader调用作为fixture ERROR。

**B先持锁，已存在首次档案。** 先真实K1 capture并负向删当前Link；B真实scanner取得Article锁后在原SQL返回边界暂停，A为同pair真实K2 strong调用。观察连接采样A被B父锁实际阻塞；释放B，修后应按既有Index零弱DML。A取得父锁后、业务DML前再设透明返回barrier，观察连接保存B已提交状态，然后释放A自然返回history_conflict、首档不变。当前基线B会真实create、A可能existing_pair_conflict；这应作为业务负结果，不把A未created当fixture前件失败。**不能要求K2 created覆盖K1。**

另保留“从无Index、B普通弱写先完成→A强写existing_pair_conflict”的普通policy控制：UNKNOWN_NO_INDEX不要求B零写或A必created。不能为新测试偷换成C254旧未来全UNKNOWN拒写顺序。

**C261补充RR旧快照负控。** B在测试自行建立的真实外层事务中、任何MVCC读取前仅对该测试事务设置REPEATABLE READ（不是修改session/global，也不是产品guard降级隔离）；记录SHOW transaction_isolation、backend PID，再以真实普通SELECT/只读pair reader读取目标pair无Index，建立旧snapshot。A另一个真实连接随后按原窗口A完成正常capture并负向删Link，保持Article锁等待释放；A不更新Article，独立连接记录其Article完整行前后相同。B通过既有task/scanner或真实reprocess进入父锁语句，独立连接采样B被A实际阻塞后释放A自然提交；B取得父锁后仍处于同一外层RR/backend，不能靠该父锁假定快照刷新。

正确集成应在弱get_or_create/delete/update前取得实际RR并报上述稳定内部事务错误；不接受“任意异常/恰好40001”冒作该门禁已验证。原基线没有门禁而实际创建/改动关系，是有效缺拒绝业务FAIL；若环境、权限、线程或父行被另行更新导致测试窗口不成立/先发driver错误，保首因并列前件ERROR，不算门禁PASS。测试不能依赖未来异常类的setUp导入；实际调用后记录真实异常类名、稳定代码、事务级别、backend、是否到达弱DML及完整SQL。不得在reader返回NO_INDEX时截获改值，不允许产品代码另开RC连接或重试逃过此输入。

覆盖article task→reconcile、profile/global写入单位，以及已有外层`_commit_article`→reconcile的真实重入。直接scanner/_commit_article验证稳定异常分类；外层公开`reprocess_article_entities`保留原status=failed/error口径与`article_entities_reprocess_failed`审计，不为返回异常类型新增API。其tags/metadata/成功审计应随article事务回滚，失败审计单列；任务错误不得新增成功扫描日志。RR自身可能仍看不到A的新Index，因此最终关系/原日志/Index零弱变化必须由**独立RC观察连接**在A提交、B事务退出后读取核实，不能拿B旧快照下的空查询冒全局零写。

另在无并发冲突的真实SERIALIZABLE事务验证同一拒绝分类（其他不支持/无法确认级别也拒绝），并保留只读pair reader在RR正常观察、不新增可写准入限制的控制。测试输入的事务级SET只在fixture边界，SQL原件区分setup与产品调用；测试结束按原事务提交/回滚收尾核对连接状态，不改session/global。原两个RC窗口、budget与有界cleanup不放宽，不把RR失败扩成全站无index历史enforce。

每窗口保存两个distinct PG PID、实际blocker样本、完整原SQL/params/主FROM/JOIN/OF/线程/执行状态、barrier顺序、B提交时的实际行/日志/Index、A真实结果、最终archive绑定、异常和有界清理。使用C258同类透明SQL观察，不改变SQL/返回值，不按JOIN子串误标，不sleep假装blocking，不mock两个writer成功，不复制假业务服务。线程/场景错误先保首因，所有barrier/cancel/join在finally释放。

## 9. 推进与范围截止

只要此方案获原R_C审、ROOT下发下一测试源卡，接缝依赖已就绪：先固定真实新测试/精确登记与原件责任，再授权原固定基线首次RED；有效业务FAIL后才最小实现并新SHA正常CI，不rerun旧对象、不改oracle凑P。原marked/manual、普通NO_INDEX独立policy、同pair首档和不同K冲突均作回归。

不新增迁移/backfill/enforce、来源权威、保留/擦除/role/cutover授权；不修改D模板或公开读取/计数。未索引旧强历史、跨identity/ID合并、生产同凭据owner伪造/删表、全L02自动防复活都未解决。若实现时发现现有接口无法维持NO_INDEX/候选未知的区分或真实SQL锁行为有问题，具体报告ROOT后停，不制造新record-only重复slice。本卡仅此设计固定后交ROOT→原R_C，停止等下一授权。
