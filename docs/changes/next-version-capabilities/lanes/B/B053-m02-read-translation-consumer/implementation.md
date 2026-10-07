# B053：组合consumer阶段候选，E03正常前置与真实RED准备

状态：`STAGE_SOURCE_CANDIDATE_PENDING_ORIGINAL_R_AND_ROOT_NATIVE_WINDOW`。此阶段只实现E01/E02真实RED所指的组合缺口，并提供真实初次完成态以供E03正常源码前置。E03重投修复尚未实施，必须先取得真实目标RED；另外七方法仍待后续阶段。不是完整B053/10/35 GREEN，更不是完整M02。

## 基线、授权与已接受证据

独立分支 `codex/b053-m02-read-translation-consumer`，工作区 `/Users/mentianlu/.codex/worktrees/b053-m02-read-translation-consumer/umanews`，从固定B051 `961b0c8697ff06f8a2f6f62e723a49772778ca10` 建立。原a14d cwd不存在，create_worktree返回Not a git repository，遂在可用B051 checkout上执行git worktree add；app attach报告非managed，磁盘Git worktree/branch有效。没有切换/修改任何旧checkout。

范围依据已审B050 `fd7b0772ceacbda855ee5a953a33bde4ae5178bf`，原R `e65d7247` 关闭R01–R03。原R `0d45b797b4a337af31d1941d4dd1eb0551640399` 接受B052两条真实目标业务RED，receipt SHA256 `83905ef786004195f7a1668e78dc854704bf4dfc67551b0ff0c14bcd8d33abb0`，6349 inputs。

原实际report `7e728cdae5800b685e840458e69f476ccdc9a6d3d479952c97c36a7ee6fe9157`、official log `d08ef157748e72dd68377b7a5b51958a6c4fdd6060233e115ef841d2dbae5bdc`、cleanup `2f195538d75c1ffc56204178cb0d24143522e2bae28a1af2498e137d035a5419` 均保留。E01/E02顺序各命中目标FAIL、前置ERROR0；未到达的E01全文/Article与E02缓存/计数后续断言仍需实际GREEN。

已有任务授权覆盖本地实现与阶段commit；根AGENTS的G1范围已明确。没有共享主线或生产动作，不进入G2/G3。实际窗口仍仅ROOT拥有；没有新agent、PG/Docker/共享锁/provider/CI/network或push/merge/deploy操作。

## 实现与写入边界

- `managed_readonly_translation.py`：登记路由仍先于普通prepare/provider。私有consumer仅在原parent/read scope、封闭SDK/reader、完整codec与锁后identity/grant/version/source/deadline合法时进入。
- read阶段复用原B049执行器：claimed仅私有prepare一次；E02 executing+已提交read按原ledger安全复用。read_ready写真实step UUID/SHA，不替换完整原正文。
- 私有provider继承原翻译解析/术语/质量流程，消息增加真实摘录和程序provenance，正文仍为原完整材料；仅构造原closed offline client，公开provider guard保持不变。
- 每次模型请求锁parent→read root→Article→Run→step→request ledger。首次read_ready→model_started owner CAS与原core `_reserve_locked` slot1在同txn；提交后当前scope/PID/thread owner才调用SDK。第二轮重核同owner、当前权限与原usage对账；至多两次预留，不增加费用账。不持业务事务/行锁调用SDK。
- 授权提交后撤权可能仍有该permit的一次在途调用；timeout按剩余原期限收紧，返回usage忠实journal，未知usage拒绝保存，下一轮/save/final重新查权限。fresh model_started/blocked不接管，不退款、不关闭活跃赢家；模型/读未知只由当前获准writer保存固定gap原因。
- checkpoint：外部metadata先全次拒绝reserved keys，私有wrapper才加入程序provenance；当前read权限/实际ledger与结果写入、checkpoint_saved在同txn，slot/read旧证据不回滚删除。
- final：当前围栏锁仍持有时调用从原finalizer逐条抽取的Article应用primitive，再CAS写Run SUCCESS/claim completed/final_applied/不可变final receipt；同txn失败全部回滚。成功后才返回translated=true。checkpoint_saved fresh scope可免费续apply；E03 completed重投暂仍由原claim fence拒绝，等待独立真实目标RED后修复。
- `translation_recovery.py`：公开decoder仍拒绝注入的provenance；私有decoder只接受程序指定的完整canonical JSON provenance（bool/int差异也拒绝）。抽取Article写入primitive，旧finalizer自身权限检查和terminal writer保留。
- `tasks.py`：仅新增接收私有consumer的已提交dict结果分支；ordinary guard/legacy接线保留。

原translation.py、预算core、B049readonly服务/0081、原23及预算fixture字节保持。原公共reservation/claim history/locked claim/prepare/save/terminal writer AST保持；无生产flag、工具列表、表或迁移变化。

## 测试阶段与阻塞

本阶段保持E01/E02两个方法及原目标/后续断言AST不变。E03先真实user retry→登记→consumer取得Article/Run/final，再进行fresh同envelope重投；正常完成前置仍使用fixture_requirement，失败是ERROR。新增观察打印及收据断言说明，不手填checkpoint/final/终态，不mock业务授权或保存成功。

下一窗口建议拆分固定manifest：exact E01/E02预期PASS，再单独exact E03预期命中“真实registered完成态重投未返回同一final receipt”的目标FAIL。尚未有SOURCE/host review与allocation，此处只是准备；若E01/E02后续断言/实际完整前置失败，先按真实错误修复候选，不将E03前置ERROR算RED。

10个子场景/35条义务保持，源码目前仅新增3方法，设计35仍不是collect/executed分母。`obligations.json` 为完整固定映射：E04–E10尚未创建，不补空方法，不把现有33项纯校准冒充35业务GREEN。E03真实RED及对应修复后，另七方法和并发/存储/撤权/期限矩阵仍需完整源码准备、原R审、ROOT实际GREEN。

runtime `/Users/mentianlu/.codex/runtime/b053-m02-read-translation-consumer-001` 提供source archive/manifest、完整diff、原R报告/receipt、原件保护、阶段exact名单和设计35映射。20项codec+13项checkpoint/provenance纯AST提取校准通过；只是合成JSON与源码兼容校准，没有业务module import、Django collect或native执行。真正CAS/DB rollback/锁等待/权限/SDK计数/全文与最终Article必须在ROOT实际窗口验证。

## 后续交接及回退

先将固定候选与阶段包交ROOT→同原R源码审；批准后另建inactive host包→原R host审→ROOT新exact allocation。禁止复用B052原allocation/执行state。E03正常前置真实成功且目标RED被接受后才修复completed receipt入口，随后完成其余七方法和完整35义务；原formal/full由ROOT/C负责。

回退仅停止新私有登记，保留持久登记guard/codec及兼容consumer；不删plan/progress/final/read/request/checkpoint，不重置UUID/期限、不普通provider fallback、不新claim接管unknown。保留原所有候选/执行/审查证据。

完整M02仍缺真实模型规划、真实累计token/每日费用、跨进程授权、生产Celery/ack恢复、outbox/公开发布幂等与production验收。此阶段不宣称这些能力完成。
