# C264 固定源码首次自然 PR 正常 CI 结果

本次已取得真实业务/需求 RED，尚未实施 guard；固定包交 ROOT → 同 R_C 结果审。不能把全部 unittest FAIL 当作各自完整命名合同都已验证。

## 固定对象与运行

- PR264；唯一普通 nonforce push 将远端 c71438554 更新至 HEAD `69e9856282a41048ac9434fc1928c0d9fc53359f`，TREE `2536f738d6be9083441481ae0347199a1524e57d`；短时 OS flock 内完成，自动释放。
- 自然 pull_request run **40104839417/1**，2026-10-24 **14:58:12Z–15:19:02Z**，没有 dispatch/rerun。base `1dd5e0a508957672bcddd1c33e454fbbef1b75c1`；实际 test merge `c42fd9b4fa070ce3497c74214b3d53fc4bc80ddf`。官方 commit metadata 证实 merge 两 parent 为该 base/head，tree 精确相同。
- 新test SHA `502c5625c865df81f5c56685c9f4c18a593b191abe67d466134687788a051557` / catalog `8da0453cf2dfc3fc104e6907fc8054011d99cd787f992b6c98d731a0b98cb231`；26 pins与源码均未变。tracked clean，唯一预存设计untracked保持b547，未提交。

## 原始分母

|范围|原生方法|PASS|FAIL|ERROR|SKIP|
|---|---:|---:|---:|---:|---:|
|新scanner suite|24|2|22|0|0|
|旧pair receipt index|27|27|0|0|0|
|旧diagnostics|20|20|0|0|0|
|旧strong evidence protection|15|15|0|0|0|
|旧binding persistence|17|17|0|0|0|
|旧profile strong trigger|13|13|0|0|0|
|本次full|7091|7059|22|0|10|

新suite **72条失败条目**来自22个原生方法（含subTest），不与原生分母混加。全部失败仅在batch-010；50批均lifecycle=complete，49批exit0、1批exit1。7091计划ID/JSON实际登记/literal RUN零缺失、重复或额外；RUN顺序与实际登记逐批一致，29批计划顺序不同但精确ID集合相同。详见plan-execution-registration与legacy-suite-results。

新suite通过的两项为现有manual/removed/marked优先保护和只读真实RR reader；没有新skip或setup/import/worker ERROR。81次弱调用trace中reader调用均0，93份全trace（含12 strong-control）、651条C262原事件全部保留。

## 逐方法边界与首因

per-method-triage.json逐一保留24方法、72原始traceback、SQL/DML和原事件定位。20个方法的业务/需求断言失败包括实际受保护关系被改/删/重建、无history观察、未拒绝实际非RC写入、preview在新capture后仍含create、16/17动作预算以及elapsed应拒却实际删除。不同K当前fixture准入、坏candidate等前件未报ERROR，但后续未到达的断言不据此宣称已验证。

**两项driver控制单列 NOT_REACHED/ERROR-for-SQLSTATE-claim**：真实driver三SQLSTATE+public failed-audit方法在Index读取缺失时未注入故障，faults=[]、SQLSTATE=null、无异常；原unittest仍记录FAIL而不是ERROR。原件另可见每次受保护pair实际弱UPDATE，但不能称已获得22012/42P01/57014回滚或失败审计的完整RED。不存在借future guard缺失造NOT_READY的情况。

elapsed原事件实际0.026144079秒、delays=[]，基线没有Index读，因此没有注入5.1秒等待；实际删除16条关系（1条DELETE SQL）及状态差异构成业务FAIL。5.1等待和新guard超时/恢复分支尚未执行，不能声称通过。正常GUC用例先在关系变化处失败，后面的最小值/恢复断言未到达；16对照用例实际普通删除达到预期，但因0history读失败，32SELECT/64MiB动态上界仍未证。ordinary NO_INDEX弱create已见，后续strong conflict断言因先失败未到达。preview保持只读的检查先通过，capture后preview未过滤；后续commit段未到达。

首条业务失败：`test_RC_strong_first_actual_parent_block_then_no_weak_recreation(path=article)`，实际capture后负删旧Link，B被A的Article锁阻塞，A自然提交，B真实创建新Link42（article38/profile39），check_preserved因links改变失败。正式stage在全部批次结束后 **15:18:53Z execute-isolated-plan exit1**，其first_failures原件首项即上述失败。

## 真实并发原件

12次pg_blocking_pids均真实命中；完整Article/Profile/Identity/Link锁SQL、FROM/JOIN/OF解析、PID/isolation/xid和执行状态见concurrency-raw-evidence.json及batch-010.log，不补造SQL或结果。

|窗口|A PID|B PID|实际blockers|原始结果|
|---|---:|---:|---|---|
|RC strong-first article|109|111|B→[109]|A created自然commit，B created1；当前Link42|
|RC strong-first profile|113|115|B→[113]|B created1；当前Link44|
|RC strong-first global|117|119|B→[117]|B created1；当前Link46|
|RC strong-first reprocess|121|123|B→[121]|B committed；当前Link48|
|RC weak-first article|128|126|A→[126]|B created1；K2 existing_pair_conflict；Link50|
|RC weak-first profile|132|130|A→[130]|B created1；K2 existing_pair_conflict；Link52|
|old RR public reprocess|153|151|B→[153]|B committed；独立RC PID149见Link175/Index86|
|old RR article|158|156|B→[158]|B created1；RC PID154见Link177/Index87|
|old RR profile|162|160|B→[162]|B created1；RC PID154见Link179/Index88|
|old RR global|166|164|B→[166]|B created1；RC PID154见Link181/Index89|
|old RR both|170|168|B→[170]|B created1；RC PID154见Link183/Index90|
|old RR internal reprocess|174|172|B→[174]|B committed；RC PID154见Link185/Index91|

6个RR窗口均由B真实旧RR reader得到NO_INDEX固定快照；A实际capture+负删，Article全行前后SHA相同。B无40001/隔离拒绝，实际取得父锁后继续写；末态由明确独立RC observer读取，archive历史Link与新current Link不同。2种RC窗口的自然worker收尾/强先行commit事件、弱先行main观察、state_comparison均保留。RC strong-first最终state_comparison有真实main末态行，但没有单独emit该main observer PID/level；不把源码setUp的RC前件冒充额外原事件。RR独立末态metadata则原事件完整。

12窗口均alive=[]、24 worker closed=true/trace=null，总时0.091–0.198秒，未放宽30秒总预算。这里证明测试worker有界收尾，不证明远端CID/容器全局清理。

## 正式gate、skip与未验项

本次static-contracts/generate-plan通过；execute失败，verify-execution、独立collect、image upload均SKIPPED；evidence上传成功，test-plan-gate require-complete-plan于15:19:00Z exit1。**本次正式首因不是expired-skip**。10项skip与catalog理由精确匹配，但review_by原值2026-10-16已过期；仅stdlib静态对比，未本地运行verifier/改期限。C259正式expired-skip FAIL及C259 pre-RED NOT_RUN历史保持；C257首失败不被覆写。

image仅记录执行计划image_id `sha256:083e1eb849910314c9a835c6c1c8caf098803dc2a20188a879c99782db08a3ca`；image artifact未上传、body未下载/验证。独立collect未执行，不能拿本次计划内部collection冒充它。正式summary不存在。外部CID/远端清理UNKNOWN；本地只读watcher进程已退出。没有生产DB/Redis/第三方访问、镜像body或依赖下载。

## 封包与下一步

官方evidence artifact12563864499：1175696B/104成员，SHA dc13c232cce5a3adffbd728274bc250d8751d5d0f7166ec4030a5858ff534af4，匹配官方digest；官方logs ZIP32981B/16成员，SHA c85c4e37bd40690beb49092f7784650ac57df695975882f9317d7ced58aae8cb。ZIP CRC/成员路径和读取校验通过，原件保留。历史72包/5587成员seal及全部bytes/SHA匹配。

仅完成本次一次正常RED及结果保全；没有改test/产品，没有rerun/第二run/dispatch。ROOT应先转同R_C结果审，之后才另卡决定最小guard。本卡停止，不称交付或整L02完成。
