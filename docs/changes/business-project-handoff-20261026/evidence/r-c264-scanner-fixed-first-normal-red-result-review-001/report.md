# R_C264：scanner固定首次正常RED实际结果复核

结论：**APPROVED — REAL_SCANNER_REQUIREMENT_RED_ONLY / MINIMAL_GUARD_IMPLEMENTATION_BASIS_ACCEPTED**。已有真实weak写坏索引保护和非RC准入要求的证据，可交ROOT另派最小horse_profiles guard实现源卡；无必须先改测试/oracle的新finding。**24原生2P22F不等于22份完整命名合同RED**：20方法业务/需求FAIL可采，2个driver控制未到达，后续还需真正运行其SQLSTATE/回滚/审计及资源分支。不得将此结果称新GREEN、全部门禁通过或整个capture机制RED→GREEN。

## 固定对象、纠正文案和原件完整性

作者最终包 `/Users/mentianlu/.codex/runtime/c264-scanner-fixed-first-normal-red-002`。seal `c5234ac6beee86b6c9b35884650a495f76cd56e7b3fdcb88fd989edb156f8329` 的161成员22863418字节逐项核验；report `b34fbf111492db62b88d7c8cebe8256814e00a5b656c3e567b766e2956c384d0` / index `936aacf9761d880205d9857da95317eefb33d120d4f3360229d2601f9ef506fc` 与派单相符。001原seal及159成员亦重新核验保存，002只纠正“一条DELETE删除16行”的文字，不覆盖旧包/raw、不改执行结果或SQL条数。

唯一自然run `40104839417/attempt1`，HEAD `69e9856282a41048ac9434fc1928c0d9fc53359f` / tree `2536f738d6be9083441481ae0347199a1524e57d`；TEST `c42fd9b4fa070ce3497c74214b3d53fc4bc80ddf` 官方父顺序BASE `1dd5e0a508957672bcddd1c33e454fbbef1b75c1`、HEAD且tree相符。当前作者同HEAD/tree、tracked无改动，唯一预存设计untracked不变。26 pins、20 control blobs、rules/catalog规范摘要匹配；72历史包seal及5587成员逐项保存核验。

artifact12563864499的官方evidence ZIP1175696字节/104成员，SHA `dc13c232cce5a3adffbd728274bc250d8751d5d0f7166ec4030a5858ff534af4` 与API digest相同；官方日志ZIP32981字节/16成员，SHA `c85c4e37bd40690beb49092f7784650ac57df695975882f9317d7ced58aae8cb` 为本地核验值。各ZIP成员与保存原件逐字节相同。

本审直接以自写标准库解析原native JSON/log/ZIP及只读Git，不执行作者reader/helper、候选、probe、测试、SQL、DBCI或网络，不写作者树/旧包，不修或重跑。

## 原生分母与真正首因

独立核对50批均complete，49批exit0、batch-010 exit1；execution-plan规范SHA `812e8faf1e5d8139f47a66034a6373557bc2cae2d9716370e692f433938f89b4` 与各batch run/attempt/tree一致。7091 planned unique/executed unique/raw RUN，**7059 PASS、22 FAIL、0 ERROR、10 SKIP**。7091行literal按实际报告顺序全部匹配，无缺失/额外/格式例外；29批plan枚举顺序不同但集合/数量一致。

新suite24方法=2P22F，原失败rows72（含subTest）只归并22父方法，不增加分母。2P为既有manual/removed/marked优先和只读RR reader，说明原保护/读取合同仍工作；没有NOT_READY/import/setup/worker ERROR。旧pair-index27、selected20、marked15、writer17、trigger13全部fresh PASS。

首条新业务失败为RC strong-first/article：A真实capture后负删Link并自然提交，B实际父锁等待后创建新Link42，pair Article38/Profile39，state_comparison从[]变成该行，Index摘要未变。正式当前首失败stage是15:18:53Z execute-isolated-plan exit1；不是expired-skip或缺API。原trace及first_failures与实际行变化相符。

## 651事件与真实保护缺口

直接从batch-010.log解析651条C262事件。93份actual_call_trace含81 weak、12 strong-control；81 weak trace的reader_calls全为0，说明现基线未调用新增索引guard，不是reader/API缺失。67 actual_three_piece_capture独立逐份核canonical原件、真实link full after/SHA、log/Index原字节、K重算、pair/PK/历史actor绑定，均成立；这只证明隔离真实producer/capture前件，不认证来源或生产许可。

实际弱改/删/重建、缺history观察、非RC未拒绝、preview在新capture后仍含create、17pair未拒绝等可构成真实业务/需求FAIL。不同K前件通过真实history_conflict准备；坏候选由真实捕获后的owner负控确认，不伪造两个准入成功。后续断言若已被较早失败短路，不据此宣称完成该方法名下全部合同。

**driver两方法独立标未到达**：6份actual_driver_result均faults=[]、SQLSTATE=null/error=null；public reprocess故障控制亦faults=[]且status=committed。没有Index SELECT故未注入22012/42P01/57014。native仍FAIL，不改计ERROR；语义上是NOT_REACHED/ERROR-for-SQLSTATE-claim，不能称三SQLSTATE回滚或失败审计已经实测RED。可见真实weak UPDATE执行，但不捏造未输出的独立单语句rowcount。

elapsed原结果0.026144079秒、delay=[]、error=null，未注入5.1秒；其state_comparison真实16行变[]，weak_DML只有**一条DELETE SQL**。因此关系保护/应拒绝而继续写的业务FAIL成立，elapsed超时和恢复分支本次未达。16pair普通删除本身达预期但因0history观察失败，不证明32数据SELECT/64MiB动态界；正常GUC方法在关系变化处先失败，后续最小值/恢复断言不能按方法名认定已验。普通NO_INDEX弱写先见，后续strong conflict因先断言失败未到；preview初次无写验证通过，capture后preview过滤失败，随后commit段未到。

## 12个真实PG窗口

独立核对12份pg_blocking_pids样本holder均在真实blockers中、两个PID不同；12 cleanup均alive=[]、每窗两worker closed=true/trace=null（24worker），总时小于30秒。78条窗口锁SQL原始行引用逐一对应事件，主FROM/JOIN与分类相符，PID属该窗口、语句completed且真实execute；不把78条语句或主标签当tuple锁数量/内部锁序认证。

4 RC strong-first窗口Article/Profile/Global/Reprocess均A created自然commit后，B真实重建；当前Link依次42/44/46/48。2 RC weak-first先有K1档案、B先持父锁后创建Link50/52，K2真实A等锁后返回existing_pair_conflict，不能要求K2 created或把合法冲突当前件ERROR。它们正支持实现前索引保护缺失的业务断言FAIL。

6旧RR窗口B先真实reader NO_INDEX固定snapshot，A真实capture+负删并只锁父不更新；六份parent前后SHA一致。B实际等父锁后无40001/隔离拒绝并继续创建/committed，最终Link175/177/179/181/183/185与对应Index86–91历史original_link_id不同。最终观察均由明确独立RC PID149或154完成，与B旧RR PID不同；不是用旧快照空查询假证末态。它直接支持C261实际事务RC门禁必要性。

RC strong-first的main末态完整state_comparison可见，但未另emit该observer PID/level，本审保留此原始证据边界；不能用setUp默认RC替代一条不存在的元数据事件。RR独立观察metadata则完整。锁FROM/JOIN/缺省OF按实际SQL解释，不将主关系标签冒唯一锁目标；没有scanner最终成功事件可伪造为保护通过。worker有界收尾不证明外部CI CID清理。

## 实现依据与后续GREEN必须真正到达的分支

可按已准C260/C261在horse_profiles最小实现：实际写事务RC准入、父/当前Link锁后真实pair reader、全create/update/delete前indexed/坏候选阻断、NO_INDEX仅回原policy；profile必须在get_or_create前保护。原24、source/API/catalog及预算固定，不为凑P缩断言，不需要新模型/reader、迁移、回填或全局UNKNOWN冻结。本审不提出必须先修oracle的新finding，也不自行实施。

未来新SHA正常GREEN必须真正执行：三SQLSTATE注入到达与原异常传播、整单位/外层GUC回滚恢复、公共reprocess失败审计；一次5.1秒真实读后延迟与稳定elapsed拒绝；16/17预算、逐事务SHOW/xid及DML前全分类；normal GUC最小值/恢复；普通NO_INDEX后续strong conflict；preview后的commit重读；12窗口保护后预期零DML/K2 history_conflict/RR稳定拒绝。此前短路不允许降为“已经由RED闭合”。若实现后出现fixture/driver/observer问题，按新原件报告而非改旧失败。

## 本次正式门禁与剩余限制

本次execute failure，**verify-execution SKIPPED**，无当前expired-skip/core176异常；不能搬C259实际trace。10个skip与冻结理由/过期review_by的比较只是静态风险，不另跑verifier制造结果。summary不存在，require-complete-plan失败；独立collect/image upload均SKIPPED，计划image_id不等于镜像体/可运行包验收，外部CID清理UNKNOWN。本地watcher退出不替代远端清理。

此为**scanner切片的首次实际业务/需求RED已采信**，不是将C259 capture机制历史pre-RED NOT_RUN倒写成已跑，也不是整体机制RED→GREEN。delivery_ready/full_gate仍false。全L02自动防复活/历史覆盖、durable、真实来源许可、生产role/保留/cutover等未闭合，不启用scanner生产配置、backfill、reset release、自动下架或grant。
