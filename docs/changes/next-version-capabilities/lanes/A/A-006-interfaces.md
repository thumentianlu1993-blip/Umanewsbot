# A-006 / H01 输入边界与实现说明

`horse_target_inventory.plan_inventory(payload)` 为纯JSON schema 1 planner，不导入Django/ORM/网络/队列。它不从生产读数，不创造档案或强身份，不执行writer/公开。输入只接受普通dict/list和str/int/bool/null，拒绝子类、cycle/过深/过大结构、unknown字段、非法引用、bool当int和缺证verified身份；错误仅code。固定输入ownership与canonical集合排序，输出含input/content SHA；`compare_snapshots`验证输出SHA后给added/removed/reclassified，不回写旧snapshot。

所有schema键在模块TOP/FIELDS闭集。event提供赛地local_date/precision、受证等级、current_result/current_racecard引用与独立名单人数；participation提供参赛项引用、horse级source namespace键、版本表示、明确实际start证据与状态。horse_key必须由受审producer证明为horse稳定键，赛事内runner ID不可转填；现有getter语义可复用但本模块不调用无界query或side-effect函数。identities只接受受证verified锚点作跨源profile去重；混合撤销状态/多profile冲突保留未解。受控news关联与层状态也由producer核验，不由名称相似、发布时间或门槛eligible猜测。

producer责任（未在本轮生产执行）：先核source scope/policy、schema/revision与完整输入，按有效projection pointer/明确supersedes展平当前输入，保留无指针/legacy冲突/无名单事件，字段白名单输出，不读取或传raw_payload/URL query/密钥。planner只核输入结构与明确引用，不替代真实source许可/当前runtime验证；结果永远不授予操作权限。当前JG1只能unresolved，候选单列，`complete/historical_complete`始终false，不能将容量初测或mock作为完整分母。

近期窗口固定2023-10-03..2026-10-03含边界，start证据需true；马龄只作辅助字段。历史G1/JPN1/受证香港本土G1全名单包含非出赛者；JG1 historical_pending仍保留近期actual-start。unknown date/precision、未知start、缺名单或身份冲突保留candidate/缺口而非伪造0；独立未知人数事件另计，不加成假马数。未来30天/当日、证据赛季、新闻90天、最近实际start、明确未完成模块数量/key决定排序。layer.incomplete_modules为非负int/null，未知不提权；public状态不替代模块优先。cache/staging/profile/public独立计数，starts=null与0分开。

`h01_readonly_count.py`默认CLI仅输出12个固定SQL模板及参数/SHA，不连接。`--execute`需批准脚本的实际SHA和绑定revision格式，只读凭据从私有H01_READONLY_DSN读，不输出DSN。revision是调用者证据声明，本工具不自行证明容器revision；root须把脚本SHA/应用revision/SQL模板/schema/索引绑定精确取数包。工具以RR READ ONLY、SQL5秒/锁250ms/idle5秒、整体120秒、<=24SELECT、500聚合行、2MiB执行，异常/预算/missing schema立即partial，不重试，所有路径rollback/close。schema检查19表必要列，索引仅报告存在数，不能证明查询计划最优或schema部署契约完全一致。

SQL聚合为raw事件/参与项/已关联profile等容量预检。staging_source_id_candidates只说明键候选；profile published_at/hidden_at计数不等于真实公开可见；raw参加行不等于唯一马。没有完整loader/各地区来源覆盖、cache内容证明、身份枚举或来源权限时仍unknown，inventory_complete始终false。最近新闻上界用下日零时exclusive；不实施另包20k行/20MiB streaming。连接fake验证代码控制，不证明PostgreSQL SQL接受/真实事务或生产数量，真实PG验证如必要由root另排短窗口。

本轮无shared模型/迁移/F01变更，F03剩余35文件与真实来源缺口保留。新增测试使用纯unittest；映射proposal交root，未改共享catalog/rules。不生成假的targeted plan或把手动专项Linux运行称正式PR收据。

### 原R返修后的限时与冲突接口

等级未证历史行保留candidate/ref；新闻双引用与任何现有身份观察不一致固定拒绝news_identity_conflict，不给冲突档案新闻优先。生产读取执行入口仅固定摘要的main --execute；该入口强制fork worker及统一120秒monotonic deadline，覆盖连接至cleanup，期限kill仍存活worker后回收。直接run_counts为开发/fake诊断，不能作为绕过外层的生产调用。fork不可用fail closed；不依赖driver取消承诺。SQL按剩余预算向下取整至ms并与5秒取min。真实PG后台回滚/释放待短窗口验证，当前实际阻塞测试只证明本地worker终止，不能证明生产数据库状态。
