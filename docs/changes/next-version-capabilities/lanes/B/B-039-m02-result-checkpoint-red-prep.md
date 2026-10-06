# B039：结果检查点 RED 准备交接

任务B039-M02-RESULT-CHECKPOINT-RED-PREP-001。状态：**测试准备完成，未执行RED、未实现GREEN，待ROOT精确PG窗口**。

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
