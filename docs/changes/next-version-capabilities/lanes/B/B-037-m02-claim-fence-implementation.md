# B037：自动重试 claim/fence 实施准备

任务 B037-M02-CLAIM-FENCE-IMPLEMENT-001。当前**B037-R01 六个锁等待场景 RED→GREEN 已完成，47项受影响回归全部通过，待原 R 窄复审**；原R NEEDS_CHANGES结论尚未由复审关闭，原63项通过证据保持。ROOT 已确认原 R `6e05cc18ccc78364cb5d41babbfe4f5f367ee194` 关闭 B036-R01，APPROVED_PLAN_ONLY；该确认不是实现审核或发布授权。

从固定集成 `2c72521c55b6cdc24f7650d172b48079cbff969a` 创建独立树 `/Users/mentianlu/.codex/worktrees/b037-m02-claim-fence/umanews`、分支 `codex/b037-m02-claim-fence`。只从 `82b0c7253a4410cec7a1de31302345f2ba6f986e` 提取最终 B036 方案原字节作输入，未 cherry-pick 旧 B035 实现或 ROOT 协调记录；旧 B035/B034/C028 树未改。

ROOT 分配本线负责 tasks.py 仅 translate_article_task/必要相邻调用、translation_recovery.py 受管 claim/release/stale/terminal、translation.py 受管 run 及独立测试/B报告。models/settings/migration/catalog不改。不覆盖他线。

[测试清单](B037-m02/test_cases.md) 首批五项使用现有 selector/task入口及可控交错；目标失败是重复provider消费、旧成功/异常污染新领取、终态通知前run未原子失败及run保存失败后的状态/通知无法回滚。不依赖新函数签名，不连接 provider/mail/broker。测试准备提交仅做 AST 与 diff 检查；随后按 ROOT 窗口取得下述真实 RED，静态检查不冒 RED。

C029 释放后 ROOT 明确分配一次五项 RED 的现有镜像/本地 Docker/隔离 PG 窗口；已在固定测试提交 `a4022503945bc7dbb4f286cada1e2b547c87a2ec` 实际执行。五项 failures、零 errors/skips、lifecycle complete、runner exit1；失败分别证明重复消费2次、迟到成功覆盖新轮、迟到异常通知、通知前run未失败、run保存失败后article未回滚。不是签名/导入/环境失败。worker包含准备38.26秒、业务测试2.321秒；诊断证据不冒正式catalog/full。

独立 runtime `/Users/mentianlu/.codex/runtime/b037-m02-red-pg-window-001/red-receipt.json` 绑定SHA/tree/5IDs/镜像/PG/隔离及原日志。实际镜像 `sha256:fcf8cdaf63af51b1b8a6e30e3d2fdf871d127c3c1461bfd00c9fc6d610eab905`；官方django profile启本容器PG16、DiscoverRunner建隔离测试库；nonroot10001、networknone、readonly source/control、2CPU/4GiB、256pids、3GiBtmpfs、capdropALL/no-new-privileges。八受信控制从2c725/6e6导出并与候选字节相等，未修改控制/validator。官方worker无180秒配置，保留600秒控制超时，宿主包装570秒+30秒清理；实际未超预算。

前两启动在进入测试前分别受阻于宿主生成pycache进入controls扫描、macOS默认TMPDIR不在Colima共享面；均实测零运行容器、runner退出，错误原件保留。只改变本runtime启动环境 PYTHONDONTWRITEBYTECODE 与 TMPDIR，第三启动实际执行本五项一次。锁以FD flock自动释放并记录owner/thread/SHA/domain/PID，finally清理后实际containers=[]/runner退出，已报ROOT释放窗口。

有效RED取得后才开始三处应用代码：claim持久化固定身份/阶段/deadline/输入摘要，消费及终态统一article→确切run行锁；task受管路径拒绝外层事务、成功/异常归属核对后回写；翻译服务受管模式不选最新run/独立写终态，普通模式不覆盖受管JSON；受管终态失败同事务保存article+run，on_commit使用终态快照、robust回调，失主/回滚零通知。受管派发失败与stale只终止匹配run。实现提交当时已做AST/diff检查，尚未执行GREEN/PG真并发/相邻回归；候选固定后另申请ROOT新窗口，不沿用已释放RED窗口。

ROOT 新分配首次五项 GREEN 窗口；固定 `bb572df2fb5707062ef55f6c688fd5f0ec71d925` 上同5 IDs一次实际运行，5/5通过、零 failures/errors/skips、lifecycle complete、runner exit0。worker38.03秒，业务测试2.317秒；同官方django/隔离PG16/镜像/八控制与隔离约束。runtime `/Users/mentianlu/.codex/runtime/b037-m02-first-five-green-window-001/green-receipt.json` SHA `c067058d117b50b51e681fb2946ff9325b1abddec13281ee7a8b60b697582ac3`。finally清理后容器=[]、runner已退出、FD锁释放，已回ROOT，不复用窗口。

之后只准备测试扩展，没有新增应用代码：保留首批5方法AST和canonical IDs，提取共用fixture为无测试方法的基类；新增17项边界/两PG连接并发，包含 ordinary人工字段、force published、外层事务拒绝、源版本变化、精确deadline、领取时间不重设、旧/非法envelope、run归属、release/stale局部与回滚、通知失败隔离、真实受管服务metadata及PG并发。只对现有 recovery selector 测试的旧消息断言补入run_id/claimed_at，保持其边界/批量断言，不能继续要求无身份的旧消息契约。源码仍逐字等于首批GREEN候选。

下一诊断批申请准确63IDs：本片22（原5+新增17）、现有recovery22、M01 mock19，全部用官方django profile单runner。AST只是清单准备，尚未实际收集/执行本批；两线程PG测试需分别取得不同backend PID、记录日志并关闭各连接，不冒用顺序交错。真实正式catalog/impact/full及独立review仍ROOT后续安排。

## 63项实际结果与交付边界

ROOT 另行分配 B037-BOUNDARY-63-PG-WINDOW-001，准确候选 `9498edf185a99d6defc041cfabc714adc039d5a0`、名单文件 SHA `a1bb21a89afd550e7f575c163500dd45ff962c4869d2c762854defbb5ee1c1af`。2026-10-06 用同官方django runner/8受信控制/既有镜像和隔离资源一次实际执行全部63IDs：**63/63 PASS，零 failures/errors/skips/expected_failures/unexpected_successes，lifecycle complete、runner exit0**。业务11.686秒、worker48.33秒、整个窗口59.31秒，未超600秒上限。测试DB由容器内DiscoverRunner创建，无宿主业务库/真实Redis/broker。

真实并发测试在日志输出PG backend `[93, 94]`，通过不同PID、同轮1 provider/1成功/1跳过及线程退出、各线程连接关闭的断言。没有额外SQL observer，最多主连接+两线程连接；宿主docker top轮询只采样到峰值1，短并发未被采样捕获，**不把该峰值采样作为并发或全时连接数量的独立证明**。有效并发证据是实际PG16的测试同步、两个不同backend PID及通过断言。

独立runtime `/Users/mentianlu/.codex/runtime/b037-m02-boundary-63-pg-window-001/boundary-receipt.json` SHA `03653f29df7a5282fdbd4e2ba6da7e598f3e6a0422a747044b9f7e7c188d0bf5` 绑定完整63IDs、report、原日志、container inspect、控制来源、进程观察与清理。owner PID88682 / runner88728，finally清理后containers=[]、runner退出且窗口FD锁释放，已回ROOT释放；后续文档提交不修改任何受测应用或测试字节，不要求重复业务测试。

通知回调失败用mock制造，robust日志符合预期；测试报告零error，真实模型/邮件/外部消息调用数为零。普通人工字段、force published、源变化/deadline、精确run、普通服务JSON保护、失败/成功/回收/释放原子回滚、通知无事务与失效零通知、M01关闭/单次请求和旧provider选择等本批断言通过；不借此宣称全站或所有翻译场景已验收。

本地最小片可交原R独立代码review。新增模块catalog登记、共享tasks影响计划及required full由ROOT/C完成；当前63项是明确授权的精确诊断，**没有正式collector/catalog/full交付收据**。没有push、PR、合并、部署、生产写入或模型开关启用。完整M02累计费用预算、未知用量、跨版本响应恢复/复用与可靠下游派发仍缺，不能缩分母或称M02整体完成。

## B037-R01：锁等待跨截止时间，RED 准备

原 R 审核 `25ae204fff05cfcbaf8a6541ba050e053f700cba` 指出唯一P2：consume/finalize在取得两个行锁前固定now，等待期间跨deadline仍可能按旧时间消费/写成功/写terminal并通知。该静态反例不在旧63项覆盖内，不能以旧PASS当新反例已通过。

派单 B037-R01-POST-LOCK-DEADLINE-REPAIR-001。当前只增加三个针对性方法（每方法article/run锁各一subcase）与本B文档，不改应用实现。继承原fixture但不改原三测试类AST或旧方法；仍从selector捕获实际envelope。

新类 `stable.test_translation_claim_fence.TranslationClaimPostLockDeadlineTests`：消费、成功、terminal异常三个路径。主线程一条PG连接持目标行锁并用其自身连接查询pg_stat_activity、清stats snapshot；worker第二连接实际执行task。明确观察该backend的对应表FOR UPDATE处于Lock等待后才推进注入时钟；article锁精确到期、run锁过期一秒，claim身份/阶段/源内容不改。成功/terminal通过mock provider事件让消费先提交，再在回写前制造锁竞争。修后应保持article/run状态快照、返回claim_expired；消费provider=0，成功/异常只有先前那次provider且后续零派发/通知。线程有界join、finally关闭自己的连接，日志保留每次backend/锁等待；不用额外SQL observer连接。

C032当前占用PG。新RED候选固定后只申请准确三IDs一次官方django隔离窗口，单runner2CPU/4GiB/256pids/3GiBtmpfs/networknone/nonroot/readonly/capdropALL/NNP，最多主持锁/观察+worker两条PG连接，整体600秒含30秒清理。worker目标180秒但若官方无独立参数沿原600秒控制。没有启动容器/DB或运行新例；得到有效业务RED后才只修取得锁后的执行时钟检查，不延长deadline、不扩大M02，修后受影响回归再报新窗口并返同R。

ROOT 随后分配 B037-R01-THREE-RED-PG-WINDOW-001；固定 `5b7031939c38120c6df8f2b5589607ea7ee763d4` 准确三ID/六subcases一次运行，3tests/6failures/0errors/0skips、lifecycle complete、runner exit1。必须分级：run锁三subcases的consume69/success74/terminal79均实际观察PG Lock并在状态快照断言失败，属于有效业务RED；article锁三subcases失败在SQL观察匹配，不推进跨deadline，**不能计入目标RED**。业务16.466秒，整个窗口64.41秒，finally清理containers=[]、runner退出、FD锁释放，owner3912/runner3958。独立runtime `/Users/mentianlu/.codex/runtime/b037-r01-three-red-pg-window-001/partial-red-receipt.json` SHA `7148726e042c5b483c90a7f6fdd849c989b0cf75dc3889eefb4783baaf54e5c7` 明确分级且保存原日志/约束/结果/清理。

首轮观察器要求PG活动query的FOR UPDATE尾部，而完整article SELECT较长；该谓词对可能截断的活动文本不可靠，本轮未记录query长度，不能冒称已测出截断根因。只修测试为Lock+对应表+pg_blocking_pids包含主持锁backend，记录owner/worker/query bytes/track_activity_query_size；主持锁连接本身作观察，不新增连接或修改PG配置。三个应用源码仍不变，首轮不机械重跑，固定新测试SHA申请同三IDs的新窗口，补齐六场景后再进入锁后时钟修复。

ROOT 新分配 B037-R01-OBSERVER-REPAIRED-THREE-RED-002；固定 `029c050dfd65c643ccc2beb6a385a56e119a2492` 同三ID一次执行，六个subcases均在状态快照断言实际失败，0errors/0skips、complete、runner exit1。六条对应table的Lock等待与blocker均实际匹配：consume worker66/68→blocker64、success71/73→69、terminal76/78→74。article查询文本1023bytes、run643bytes、跟踪上限1kB，证实旧观察谓词缺陷，不修改PG配置。业务1.345秒、worker36.71秒、whole47.26秒；finally容器=[]、runner退出、FD锁释放，owner8093/runner8135。runtime `/Users/mentianlu/.codex/runtime/b037-r01-observer-repaired-three-red-002/red-receipt.json` SHA `ce9b19ec1b0efca6a7aea189c3bc2a8d6c4aadc21ef0c43f584b4a635b22dc3b` 保存准确3ID/6目标失败/6锁观察及原日志/隔离/清理；首轮部分证据不覆盖。

得到全部有效RED后，仅把 `_locked_translation_claim` 最终deadline判断从锁前now改为取得article/run两锁后的 `timezone.now()`，保持可注入执行时钟及 `>= deadline` 精确边界。没有修改deadline、field/metadata保存规则、重试/预算、ordinary/force、通知/派发或其他两个服务文件；未运行GREEN。

申请下一精确诊断47IDs：新三例+原本片22+既有recovery22，一个官方django runner，max3PG连接（原单消费并发需主连接+两worker；新锁等待仍两连接），沿既有单容器资源/600秒含30清理。原M01 mock19不再次执行：其服务/测试、settings与legacy provider factory字节均未变化，且不调用本锁后deadline helper，保留先前63PASS中的对应证据；正式full仍ROOT/C安排。固定新SHA后等待ROOT明确GREEN窗口，不沿用已释放RED资源，不把旧63PASS当此修复已通过。

ROOT 接受受影响47ID范围并分配 B037-R01-GREEN-47-PG-WINDOW-001；固定修复 `ef50b1c74d043fc80877db393814fec6fc052be2`、名单 SHA `7b03ba6fc3fff9e3a008dbfa1945fbcb34a6407511c40da6096e59905b4e9e87` 一次实际执行 **47/47 PASS，零 failures/errors/skips，complete、runner exit0**。六新子例均有实际Lock+blocker后跨截止与状态/调用断言通过：consume worker96/98→blocker94、success101/103→99、terminal106/108→104；旧单消费者两backend92/93也通过并关闭连接/线程。旧M01 19证据保留，不改formal/full分母。

业务11.760秒、worker48.11秒、whole59.04秒；原8受信控制/既有镜像/隔离与资源约束保持，max3PG。finally容器=[]、runner退出、FD锁释放，owner11844/runner11893，已回ROOT释放资源。独立runtime `/Users/mentianlu/.codex/runtime/b037-r01-green-47-pg-window-001/green-receipt.json` SHA `aafa9a62588bc9dd67f092f1695ecd4b98e35d303351aba5e195dc4e1ff621a9` 绑定准确47IDs/6锁观察/原日志/结果/控制/隔离/清理。后续只回写两文档，受测应用与测试字节保持ef50相同。

返修交原R限定复审B037-R01：只有锁后实际时钟guard变化、注入时钟/固定deadline/精确截止边界不变，测试覆盖两个锁及消费/成功/terminal。没有取得同R复审通过前，不交C集成；没有PR/push/主线/生产/真实调用/模型启用或预算续期。完整M02及正式catalog/impact/full待办继续保留。

边界保持已审方案：普通/force兼容、指定受管run、外部调用无事务、article+确切run同库原子终态、同轮fence与提交后终态snapshot通知。累计费用预算/SDK跨轮边界、响应恢复、可靠outbox仍是完整M02缺口，不扩大本片。只使用已分配现有镜像的临时隔离测试容器/PG，无生产或真实业务DB/Redis、模型调用、外发、QQ/后台扩张、push/PR/合并/发布或新资源构建。
