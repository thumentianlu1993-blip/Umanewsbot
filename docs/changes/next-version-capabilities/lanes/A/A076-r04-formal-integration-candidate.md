# A076：已审R04纯片正式集成候选

仅候选，待ROOT排原R集成窄审；无push/PR/full CI/merge/deploy。实时只读核remote main为 `1dd5e0a508957672bcddd1c33e454fbbef1b75c1`，本地旧origin引用未冒新main。独立 `codex/a076-r04-formal-integration`／`/Users/mentianlu/.codex/worktrees/a076-r04-formal-integration/umanews` 从该对象建立，不改B136/PR250工作树/head或复用其CI。桌面create_worktree因旧会话cwd不存在失败，改用Git工作树；未重建原5482目录。

## 原blob与登记

四个代码/test原blob保持：A073 `bf2d5289900c8d1ee689ff7e2ebdb4d060cb6b46` 的race_source_arbitration/module测试；A075修复 `53c567e67875f7554fe3e5f9b00f2a992d903a62` 的race_result_arbitration_shadow/module测试。两份必要合同A073/A075文档也逐字导入，历史测试/保护计数仍只是原上下文历史，不当此候选新执行证据。来源commit/path/blob/bytes/SHA在专属runtime `source-blobs.json`。不夹带未合并R02/R03/H03其他片、N02/Q03实现；已有main文件不改变。

| 变更 | 精确登记 |
|---|---|
| 两新service paths | rules.paths → r04_arbitration＋race_results，修改纯语义时也保留现行赛果相关覆盖 |
| 两新test paths | catalog.tests → stable.test_race_source_arbitration／stable.test_race_result_arbitration_shadow；domain r04_arbitration |
| profile/owner | 两label归现行python；新domain说明为R04纯选源/普通snapshot影子诊断，不宣称writer/source |
| normalizer相邻变化 | catalog.dependencies race_results追加r04_arbitration，保留旧deps/labels；race_data_sync_results.py变化不会漏掉新49项 |

不修改旧high_risk、module_initialization_full、allowed_skips/原截止、现有profiles/label、workflow/worker/runner/verifier/权限/并行/资源。未知新路径仍failclosed，不能借rules/catalog的full触发掩unmapped；目录演进仍沿原计划器校验。

## worker/profile实际合同与验证边界

现行test_plan_worker.main **先setup(profile)**；collect也先Django setup，load用unittest TestLoader，按catalog前缀归profile并拒unknown/冲突。python执行分支跳过显式PG cursor，仍import Django且受原容器isolation_probe和batch≤200约束，再用unittest runner。它不是“无需Django的全新stdlib worker”，本候选不改setup/容器或绕过它。deploy/test-impact现有Python3.12支持这些纯模块语法；本地验证解释器为已存在3.14.6。正式collect/环境导入与nativecase仍由后续准确候选CI证明。

本轮只用标准库loader实际导入两label并取得49唯一canonical IDs，逐项归现有python。两个业务类分别23/26方法，未skip，均≤200；这不是正式worker/docker collection。固定代码普通本地49项执行PASS，原业务断言/所有源bytes保持。现有mapping/Git治理三组39方法PASS：test_test_impact、test_impact_evolution、test_impact_git；临时Git fixture自动回收，无DB/provider/模型/PG/Docker/VM窗口。

独立静态验证两新module及既有race_data_sync_results路径都选择新两label且包含原race_results全部覆盖；未登记路径拒绝。rules/catalog改动按原计划器union旧/新full，本地静态计划330 labels包含原328＋新2，267 domains。**labels不是native cases**，未执行full/old baseline/PR250 CI，未宣称方法数或正式交付PASS。最终固定base/head/tree计划与hash/controls在交接runtime，不用local诊断冒Git固定计划。

## 隔离、锁与剩余义务

既有 `/Users/mentianlu/.codex/runtime/umanews-integration-lock/integration.lock` 由fcntl.flock非阻塞OS锁保护短时worktree创建、blob/登记整合及commit。元数据记录owner/thread/PID/op/SHA/resource/UTC/liveness；句柄/进程退出自动释放，不靠遗留JSON或裸lock判断存活。普通测试/静态计划不长期占锁，不争用PR250正式CI；提交前再次核remote main仍为同对象。若N02以后先合并，下一次整合必须核准确对象、保留登记并处理冲突，不能覆盖它。

仍无真实hook/writer/source、生成代次/内容时钟/health/origin/freshness producer证明；同包hash、影子建议和profile不授生产认证。真实缺项仍NEEDS_EVIDENCE，完整R04九地区/所有能力/单writer原子CAS/SLA/真实来源验收未完成。旧A070–A075成果保留，不改共享脏树或ROOT台账。下一步由ROOT先排原R窄审映射与集成对象，再决定候选push/PR及正式CI资源；本卡不执行这些动作。
