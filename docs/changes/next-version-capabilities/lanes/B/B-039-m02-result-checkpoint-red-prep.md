# B039：结果检查点 RED 准备交接

任务B039-M02-RESULT-CHECKPOINT-RED-PREP-001。状态：**首轮准确3项真实业务RED已完成，未实现GREEN，等待ROOT下一派单**。

依赖固定C033 `6793f9f2461d1382349dcc8075a7e92dea85a8ed` / tree `aa8b22d59b597d3de19205b42167338474c8c0e9`；ROOT反馈原R `0b7de5e6` APPROVED_INTEGRATION_PREPARATION，尚非formal GREEN/merge。独立树 `/Users/mentianlu/.codex/worktrees/b039-result-checkpoint-red/umanews`，分支codex/b039-result-checkpoint-red。B038原方案a7d5a056fb5c951650ec3edfe49de7ee8e6a86dc与原R30f8ec70 APPROVED_PLAN_ONLY是只读依据；原B037/B038/C033候选保持不变。

本轮只新增独立测试模块与两份B文档，不需占位接口；production三文件、models/settings/migrations/catalog/控制脚本全保持固定底座字节。授权仅本阶段准备与申请，门禁统一根AGENTS.md；未进行G2/G3动作。C034正在独占collector，B没有DB/PG授权、无测试/collector执行、无Docker/网络/provider真实调用或外发。

## 已核所有者与保留合同

TranslationRun.raw_response的业务读写集中于translation_recovery.py（claim创建/consume/terminal/stale）和translation.py（普通run metadata写、受管run不写终态）；models.py定义JSONField。前者recovery_claim_v1.phase与固定身份是受管所有者，普通服务通过has_key排除managed run。_save_claim_terminal原合并顺序会保留claim键，但其他metadata键尚无结果reserved检查；需要独立测试，不提前修。

拟定结果键recovery_result_v1保持phase=executing；完整最终中文、完整metadata、article/run/claimed/source/deadline绑定、schema/应用合同与canonical hash、usage_report/unreconciled、持久suppress快照共同构成输入。所有非法/未知合同恢复都不能fallback provider，unknownusage不归零。fixture手动seed这个JSON合同只作恢复输入；新行为必须由现有task入口完成，未在fixture/占位实现业务。

selector截获真实envelope，fixture沿现有consume变executing；首例在真实终态事务的确切run.save注入BaseException模拟退出，要求checkpoint独立提交后保留。次例通过既有入口恢复，第三例两真实PG连接争同一结果，要求单胜者。详见 [test_cases.md](B039-m02/test_cases.md)。所有provider、dispatch、通知为替身；测试准备不能称真实RED或正常fixture已运行。

## 精确首轮窗口申请

首轮3 IDs = stable.test_translation_result_checkpoint.TranslationResultCheckpointRedTests 三方法，单batch官方django profile、一次实际执行；准确名单与计划写入独立runtime，候选SHA在本次提交后锁定。需要ROOT在C034释放后另给B039专用新窗口，不能沿旧B037窗口。

复用既有trusted runner/镜像/控制、isolated PG16创建test DB；一容器、max3 PG连接、network none、2CPU/4GiB/pids256/3GiB tmpfs、nonroot、readonly source/root/control、cap-drop/NNP；沿既有600秒总窗口含清理，不build/pull、不改timeout控制，FD锁/owner/PID/SHA/heartbeat由ROOT批准后记录。一次结束finally零容器、runner退出、两测试worker线程/连接清理、FD锁释放；失败/fixture异常不借窗重跑，回ROOT。当前仅申请，未启动容器/锁/DB。

首轮预计目标业务失败分别为checkpoint缺失、未恢复translated、成功者0而非1；缺import/fixture/setup/PG资源错误不算RED。源指纹/AST/计划解析/diff检查仅静态证据。后续边界11方法不自动纳入首轮，不承诺都RED；checkpoint阶段新增锁后截止竞争还需GREEN前补齐，不用旧R01证据冒新路径。

本轮终点为正常源码fixture、固定候选与窗口申请交ROOT；不提前实施，也不改共享catalog或full分母。完整M02预算/unknownusage跨轮准入、可靠outbox/自动恢复保证仍未完成，既有DDL工期2026-10-07 18:00 Asia/Shanghai风险保留。

## 首轮准确3项实际RED（2026-10-06）

ROOT分配B039-FIRST-THREE-RED-PG-WINDOW-001，固定e44f0636020a9d28f667b3bfbb915ec23589de51 / tree f6d91a6088b031c4e0fb574e03e48116cad60324、原3IDs一次实际执行：3 failures、0 errors/skips、complete、exit1。fixture/现有入口正常运行，分别缺完整持久checkpoint、重投返回claim_already_consumed而未翻译、两个真实PGbackend都skip使成功数量0而非1。没有缺import/setup/fixture失败。它仅证明三项核心缺失，不替代边界11或正式full，也不是GREEN。

两worker实际backend68/70、关闭连接True且无残线程；业务1.069秒、worker36.602秒、whole47.501秒。原受信控制/固定镜像/隔离未变。finally容器=[]、runner退出；owner28554/runner28591经host ps不存在，FD锁重新取得/释放验证。Docker top抽样peak不能冒实际全程峰值证明，连接上限由fixture主+2worker设计和真实PID断言共同约束。

独立runtime `/Users/mentianlu/.codex/runtime/b039-first-three-red-pg-window-001/red-receipt.json` SHA `9e16f68579553345116e6feb58561906088717955736f5d16eca6bbf956a8851` 绑定准确IDs、原plan/source/8controls封存、完整rawlogs/results/isolation/inspect/cleanup。资源释放与结果已回ROOT；只文档回写，测试和生产源保持受测e44f0636字节，不续窗、不扩大、不实现GREEN。
