# B037：自动重试 claim/fence 实施准备

任务 B037-M02-CLAIM-FENCE-IMPLEMENT-001。当前**原 R 代码审核 NEEDS_CHANGES，唯一 P2 B037-R01 的三个新 RED 反例已准备，尚未执行或修实现**；原63项通过证据保持。ROOT 已确认原 R `6e05cc18ccc78364cb5d41babbfe4f5f367ee194` 关闭 B036-R01，APPROVED_PLAN_ONLY；该确认不是实现审核或发布授权。

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

边界保持已审方案：普通/force兼容、指定受管run、外部调用无事务、article+确切run同库原子终态、同轮fence与提交后终态snapshot通知。累计费用预算/SDK跨轮边界、响应恢复、可靠outbox仍是完整M02缺口，不扩大本片。只使用已分配现有镜像的临时隔离测试容器/PG，无生产或真实业务DB/Redis、模型调用、外发、QQ/后台扩张、push/PR/合并/发布或新资源构建。
