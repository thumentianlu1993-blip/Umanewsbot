# A-006 真实 PostgreSQL 专项验证准备（未执行）

代码绑定 `4e86466fff0e607d00c4cb8e63cb30c93d1b697b`；原R在 `0c307354e683909cfab1827e368f408662d1a13a` 关闭3项P2并批准local代码。32项本地及固定Linux通过，含受控驱动实际阻塞终止，尚未连接PG，不能证明服务端停止/回滚。此文仅向协调者申请B005后的短窗口，不启动容器、生产SQL或新主要实现；独立R finding优先，代码变更后重新绑定。测试标签/共享映射仍由root统一登记。

## 窗口与隔离申请

申请既有single-combo单容器（PG+Python），无并发测试；预计10分钟，硬截止15分钟（含初始化/清理），整体2 CPU/2 GiB。只复用既有本地镜像，无pull/build/网络访问。容器network none，仅容器内127.0.0.1连接本次PG，不映射宿主端口，不挂载生产配置/凭据，不接Redis/Celery/第三方。镜像实际SHA、PG版本、代码tree、fixture/harness SHA与全部退出码写私有runtime；结束按既有entrypoint停止PG并删除本容器/临时卷。共享资源未获协调者排程前不启动。

fixture优先使用固定源码的真实迁移建立19表，随后由本地fixture管理员种最小synthetic数据；reader另用非superuser、无写/DDL权限的SELECT专用角色。所有setup/故障注入只作用临时测试DB。迁移预算不够则停止报告pending，不能用手写19表通过来冒充真实迁移契约。必要时手写最小表仅作为另列SQL诊断，明确其不证明Django模型/迁移一致。

## 最小必要用例（建议7组，不是已通过测试）

| 用例 | 本地fixture/注入 | 必要断言 |
|---|---|---|
| PG01 真实schema与12固定SQL | 真实迁移、19表白名单、九地区少量synthetic赛事/档案/身份/版本指针及legacy行 | schema19行全部true，12模板实际成功，status capacity_preflight_finished，inventory_complete=false；逐模板摘要/参数hash/行数可审计 |
| PG02 边界聚合 | 固定2020、近期2023-10-03/2026-10-03、未来2026-11-02与外侧日期；exact/非exact、started/非出赛、缺日期/缺profile；一个profile同时关联事件和record | 事件/目标CTE及UNION去重符合SQL范围；raw参与行不当真马数；staging同source/id仅候选；不把news-only profile缺席误称完整目标 |
| PG03 新闻与公开分层 | 发布时间07-05 00:00+08、10-03末端、10-04 00:00+08；撤稿；published/hidden四组合 | lower inclusive/upper exclusive，撤稿剔除；公开计数按现有SQL字段而非完整可见性合同；候选link状态保留分组 |
| PG04 只读与RR快照 | reader真实连接记录SET LOCAL值；取得snapshot后另一fixture管理员连接插入并commit，再执行后续聚合 | reader read_only=on/isolation repeatable read，三个timeout精确值；当前事务看不到后插入数据，新事务能见；本地独立连接验证写语句42501且不改变fixture（失败事务不混入正常reader调用） |
| PG05 schema fail-closed | 隔离专用test DB管理员可逆RENAME一个必需列或表，commit并释放锁后，独立reader开启新RR；finally管理员恢复RENAME并commit，再独立核19表列 | 精确schema_mismatch、selects=1，无snapshot/业务SELECT、不重试；返回脱敏partial。恢复/核对失败即FAIL，不以rollback未提交DDL替代跨连接可见故障 |
| PG06 服务端timeout/lock | 独立fixture管理员持目标表ACCESS EXCLUSIVE锁，reader触发250ms lock_timeout；另列诊断调用pg_sleep验证statement_timeout=5s | driver错误返回generic partial，后续模板未执行；rollback/close并释放锁，无后台重试。pg_sleep仅测试连接故障注入，不增加生产模板/扩大生产SQL |
| PG07 cleanup与最小权限 | 记录reader backend_pid；正常及PG05/06返回后管理员查pg_stat_activity及fixture校验 | reader会话消失/无idle in transaction，数据摘要不变；临时SELECT角色无创建/插入/更新/删除权限；错误不含DSN/秘密/原SQL异常 |

fixture控制数量：最多30赛事、40参与项、12profile、24identity、20record、12article/link、12staging；都是标注synthetic的本地数据，无真实payload。分别保留期望值表；schema与真实类型依据固定迁移，不猜原生产表。PG01–03复用一份最小fixture，PG05独立DB避免污染正常用例。行/字节/clock上限已有fake测试，真实PG只补SQL/driver/服务端事务证据，不重复未变32例来替代新增PG断言。

每次run_counts仍执行120秒、5秒statement/250ms lock/5秒idle、24SELECT/500行/2MiB既有上限。故障用例不扩大预算，不盲重试。输出仅测试编号、synthetic期望/实测聚合、PG错误码的测试断言、连接生命周期与hash，不输出连接串或个人数据。新harness需原R审核/root登记路径与标签后才形成正式test-impact收据；手工专项结果单独命名，不宣称生产计数、许可、H01整体完成或主线交付。

## A007 最小执行设计（先审，新增harness尚未执行）

新增责任路径 `server/stable/test_h01_count_postgres.py`，使用Django TransactionTestCase，默认collect/run实际执行；setUpClass非PG时报错，不skip，无opt-in env/manifest开关，不新增skip allowlist。只接受隔离test_数据库、loopback host、固定Linux真实迁移。已有single-combo entrypoint在network none容器内启动PG；profile复用django，测试源码与镜像SHA一并固定。若既有profile的DB名称/角色不满足约束，先报告配置差异并让root核对，不降低隔离条件。

原4个已审Python文件字节不动，不改模型/迁移/生产writer。新增源码只用于实际PG验证；root拥有共享catalog/path/profile，本线另交映射proposal。G1范围沿用H01测试验证授权；没有G2/G3动作。原7组需求仍有效，拟收敛为下面5个method（每例synthetic fixture、独立连接清理）：

| method | 执行与断言 | RED / mutation条件 |
|---|---|---|
| test_fixed_templates_aggregates_and_select_role | 真实迁移19表、12固定SQL；日期边界/重复profile/空外键/新闻90天exclusive/撤稿/public分层的期望聚合；reader SELECT专用角色。校验schema19行、snapshot on/RR、每SQL摘要、partial/complete语义。读取角色INSERT/UPDATE/DELETE/CREATE被拒绝，fixture摘要不变 | schema/SQL真实不兼容、错误UNION/日期范围、公开误计、权限过宽应FAIL；不假定现实现必失败 |
| test_repeatable_read_does_not_see_later_commit | reader snapshot取得后由另一fixture管理员连接commit一条本地synthetic参与项；当前RR不见该行，新独立事务可见。观察真实SET LOCAL timeout值且不大于当时剩余预算 | RR改read committed、查询未同一snapshot、timeout仍固定5秒应FAIL |
| test_schema_mismatch_and_service_timeouts_fail_closed | schema子例：管理员在隔离专用test DB可逆RENAME必需列/表，commit释放锁→独立reader新RR→精确schema_mismatch/selects=1/无snapshot或业务SELECT→finally恢复commit→独立核19表列。lock子例另开管理员连接持ACCESS EXCLUSIVE且未commit，确认250ms锁超时；受控cursor另将业务SELECT替换为pg_sleep验证真实statement_timeout，partial无重试 | 缺字段继续、超时后重试/执行后续模板、敏感异常回显应FAIL；诊断SQL不加入生产模板 |
| test_cli_deadline_stops_active_backend | 测试执行真实main固定摘要--execute；受控连接在固定查询处发pg_sleep、在fetch阶段阻塞，SQL仍经reader设置timeout。observer从PG实查PID/app/role/datname，证明同PID真实active/query，再观察deadline后的停止、PID消失及该PID锁消失。用短期限避免120秒测试消耗 | 去掉main强制worker或剩余SQL限时、只给caller metadata、observer没见真实活动/kill后backend持续存在应FAIL，不能只断言客户端exit |
| test_killed_local_transaction_rolls_back | 独立本地诊断worker以fixture管理员在本次test DB修改一条synthetic记录但不commit，持行锁后阻塞；observer证明事务/锁存在。受信deadline终止后observer重新读到旧值，PID及锁消失；对照主动rollback路径 | 提前commit、只观察父进程时间、值未恢复/锁未释放、observer使用同连接应FAIL。此例是PG断连回滚诊断，绝不表示readonly reader写入 |

fixture管理员只负责本次隔离DB种子、角色和故障注入；reader创建随机LOGIN/NOSUPERUSER/NOCREATEDB/NOCREATEROLE/NOINHERIT角色，仅grant SELECT列明19表，不grant未知public表或写权限。隔离PG版本若public schema默认CREATE可用，仅在本次隔离test DB内暂撤销PUBLIC的schema CREATE并保存/恢复原schema ACL，或失败，不能仅看rolsuper=false就称最小权限。角色创建/授权/撤销/DROP只在本次测试DB；异常cleanup也必须报告失败。

最多30赛事/40参与项/12profile/24identity/20record/12article-link/12staging，所有值synthetic，无真实payload、凭据或个人数据。期望聚合写在测试源码，不用生产数量。fixture setup在真实迁移表完成；迁移失败属于环境/契约失败，不当行为RED，不转用手写表冒充。

### Schema缺失与锁故障的独立顺序（R-A007-001 P2返修）

schema子例必须先保存本次test DB表/列白名单与原名，再由fixture管理员执行可逆RENAME（优先重命名必需列；不DROP数据），明确commit并释放DDL锁。之后reader使用新的独立READ ONLY/RR连接，信息schema能看到已提交缺失状态；断言reason严格为schema_mismatch、status=partial、selects=1、queries中无snapshot及任何业务SELECT。generic database_or_input_error、lock_timeout或已执行snapshot均不能代替预期通过。

finally中无论reader成功、超时或断言失败，管理员都恢复原名并commit；另一新连接执行原19表/列schema模板确认19行全部true并对原名/fixture数据摘要核对。恢复失败或残留临时名均使测试FAIL；不依赖TransactionTestCase最终flush代替DDL恢复，不把恢复成功覆盖原失败。该子例期间不与其他测试/线程共用DB或锁；被重命名对象仅来自本次真实迁移的白名单，绝不触及其他数据库。

lock_timeout子例使用另一连接：在已恢复schema上持ACCESS EXCLUSIVE未提交，reader尝试受控业务查询触发250ms锁超时，再由持锁管理员rollback释放；不做RENAME，不把未提交DDL用于schema_mismatch。两个子例分别保留故障/恢复时点与精确结果，故障连接统一finally close；新增源码必须体现这两条独立路径。

### 独立PG观察与资源生命周期

observer是另一进程/连接，使用本次fixture管理员，application_name采用随机无敏感标记。PID必须从pg_stat_activity实查并核数据库名、用户名、query/state/xact_start；不能只收child自报PID。观察器在worker开始前已就绪，但各进程的libpq连接都在fork后各自创建；parent在fork前关闭Django连接，禁止多进程共享继承的libpq连接。采用受控IPC传就绪/观察结果，只传本地PID/布尔/聚合/时点，不传DSN。

先确认worker对应backend真实活动或持锁，再放行受控阻塞；记录deadline kill请求时点、实际query停止/连接消失时点。终止后独立observer最多3秒等待PID及相关锁消失，并用新事务验证原值恢复；这3秒是验证窗口，不是120秒执行预算延长。若未消失即FAIL，fixture管理员可以pg_terminate_backend仅收尾；收尾成功不能把原FAIL改PASS。测试observer自身总上限10秒，父进程以受控IPC/进程wait预算收回，失败时清理自己的observer/worker/角色，禁止影响别线或生产连接。

正常reader的120秒、24SELECT/500行/2MiB边界不扩大；故障测试可缩短deadline/statement_timeout，输出必须明确实际值，不能把缩短的测试时长当生产容量证明。每例总上限15秒，observer目录有PID/query-stop/lock/rollback时间证据（脱敏），新增harness全组预算90秒不含真实迁移。测试执行若失败保留日志、fixture/源码SHA/退出码，先最小单例返修，不启动full。

### 状态与交接

当前只有方案/测试设计与映射提案，没有运行新增PG harness。先请原R审隔离、角色、observer、故障注入/收尾边界；通过后静态测试源码固定，再申请B后窗口实际collect/run。源码测试不得依赖CI清理后不存在的env/manifest而全skip。正式test-impact收据由root生成；此方案和后续手工PG诊断都不代表生产取数、source权限、H01整体或main交付。发现需改原4已审文件的行为缺口时带失败证据交root，按同范围技术返修/原R复审执行，不擅自扩大产品边界。
