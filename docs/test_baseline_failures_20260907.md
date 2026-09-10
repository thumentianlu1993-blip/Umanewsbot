# 测试基线失败排查报告（2026-09-07）

> 背景：M1 全量回归时发现 `origin/main` 基线本身有 235 项失败/错误（全量 4878 项，
> 失败集合与 M1 分支逐项一致，与 M1 变更无关）。当时没有完整 stable 回归 CI；已有的两条专项 workflow 不覆盖该基线。
> 本报告记录 2026-09-07 的逐簇取样结论与处理建议，供后续工单使用。

## 2026-09-10 当前基线与收口边界

- 0078 发布恢复合同已合并并上线；PR #184 的最新生产候选 `69955960` 通过 45 项 Linux/PostgreSQL 16 发布专项，当前是完整 0078、全图空迁移计划。下节“Draft PR #181，未部署”只描述当时进度，不能再列为现行阻塞；普通代码 rollback 仍按既定策略关闭。
- 最新证据：[CI run 34319906713](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/34319906713)，4,943 tests、31 failures、257 errors、20 skipped，274 个唯一失败 ID；与前生产候选 `31bf6095` 集合相同，且无相对同环境历史基线新增失败。原“235 项”和下表 Mac 分类是旧基线，不能代替此次 Linux 结果。
- 初步按异常末行归组，105 条记录涉及事务隔离级别设置时机、31 条涉及 `runtime` 导入、28 条涉及不可逆 0078 的测试准备，另有旧发布合同摘要、nullable outer join 锁和缺失旧工具路径等；这些是失败记录数，可能含同一测试的子测试，不等同于独立根因数量或生产缺陷数量。完整输入保留在本机 `runtime/fix-release-discovery/pr184-stable-candidate.zip`。
- 当前处理顺序：按共同根因复现 → 判断应用缺陷/测试准备/过期合同 → 最小修复与有效回归 → 同环境全量核对 → 独立 review。先处理可跨模块消除失败的导入和测试基础，不通过放宽断言、批量 expectedFailure 或跳过整套测试制造绿色。实际任务状态只维护在 [roadmap 当前收口节](future_work_roadmap.md)，本报告保留诊断依据。

### 已验证的分支结果（尚未合并）

- [PR #187，`a1021dcf`](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/187) 的 [Linux/PG16 CI](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/34325933049)：4,943 tests、31 failures、226 errors、20 skipped，243 个唯一失败 ID。对照生产候选 `69955960`，31 条旧模块路径失败消失、无新增；相关两个模块无剩余失败。45 项发布合同及正式前后指纹通过。历史对照 job 因既有 10 秒性能用例波动仍标红，不表示全套测试通过。
- [PR #188 首轮，`17807a80`](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/188) 的 [Linux/PG16 CI](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/34326831655)：4,943 tests、31 failures、238 errors、20 skipped，255 个唯一失败 ID。对照同一生产候选，19 条失败消失、无新增；原 24 条事务隔离级别错误全部越过该阻塞，但其中 5 条继续报 PostgreSQL nullable outer join / `FOR UPDATE` 错误，仍未修复。45 项发布合同及正式前后指纹通过。
- PR #188 当前 `cb829735` 的 [CI](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/34333661750) 为 4,943 tests、31 failures、153 errors、20 skipped，170 个唯一失败 ID；相对生产消除 104 个、无新增。上一轮 `61afbf59` 的 3 条直接 helper 事务错误已清除；原 105 条隔离级别错误全部消失，其中 100 项通过、5 项外连接加锁错误由 #189 处理。45 项发布合同及正式前后指纹通过，证据为 `runtime/fix-remaining-transaction-tests/ci-comparison-r3.json`。
- PR #189 当前组合 `22ab56b8` 的 [CI](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/34340519048) 为 4,945 tests、31 failures、143 errors、20 skipped，160 个唯一失败 ID；相对生产消除 114 个、无新增，关联模块 24 项无失败或跳过，45 项发布合同及正式前后指纹通过。此候选以双父合并包含 #188 的事务测试修复，不能与其独立结果相加。原 `936a7be4` 独立候选为 258 个唯一失败、消除 16 个，保留为历史证据；当前输入在 `runtime/fix-reconciliation-row-locks-integrated/ci-comparison.json`。
- PR #190 `93c7029a` 的 [CI](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/34333456998) 为 4,943/30 failures/257 errors/20 skipped，273 个唯一失败 ID；原 10 秒性能失败消失、无新增，术语模块 41 项无失败或跳过。45 项发布合同和正式前后指纹通过，独立审核通过；本段从前版 #189/#190 合并段落保留该验证事实。
- PR #191 首轮 `721428a2` 的 [CI](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/34337262093) 为 4,945/37 failures/229 errors/20 skipped，264 个唯一失败 ID。28 条不可逆迁移准备错误全部消失，16 个原测试中 10 个通过、6 个暴露后续旧合同/迁移叶断言，未新增失败 ID；新增两项隔离测试无失败或跳过。45 项发布合同和正式指纹通过，独立审核通过；当时后续六条断言仍需根因修复。证据为 `runtime/fix-historical-migration-test-isolation/ci-comparison.json`。 当前 `151e2e92` 的 [CI 34343151742](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/34343151742) 已核验：4,945/31 failures/228 errors/20 skipped，257 个唯一失败，相对生产消除 17 个、无新增；7 项映射后的真实用例及相关迁移/隔离模块均无失败或跳过，45 项发布合同、Django check、migration drift 与正式前后指纹通过。原 reviewer 增量审核通过。历史对照检查只新增既有 10 秒术语性能失败，由 #190 单独修复，不能称全量全绿；证据在 `runtime/fix-migration-test-contracts/ci-comparison-r2.json`。
- PR #192 首轮 `9fef94fd` 的 [CI](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/34345529390) 为 4,945/31 failures/223 errors/20 skipped，240 个唯一失败，相对生产消除 34 个、无新增。slug 后续候选 `d68b4258` 的 [CI](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/34348998560) 为 4,945/31 failures/221 errors/20 skipped，238 个唯一失败，消除 36 个、无新增；相关模块只剩审计和加锁两条错误，两轮 45 项发布合同及正式指纹均通过。当前 `de5fb540` 已补齐审计夹具并修复官方发布可空外连接加锁，保留三类行锁及权限判断；SQLite 2 pass/1 PG skip、独立增量复审通过；[当前 Linux/PG16 CI](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/34351623147) 已核验：4,948/30 failures/219 errors/20 skipped，235 个唯一失败，相对生产少 39 个、无新增，其中 38 个为发布相关修复，另 1 个未改动性能用例本轮通过（根因由 #190 修复）。三个发布模块及新增三项 PG 回归无失败或跳过，45 项发布合同、check、migration drift、正式前后指纹通过；当前证据为 `ci-comparison-r3.json`。证据分别在 `runtime/fix-publication-test-clock/ci-comparison-r1.json`、`ci-comparison-r2.json` 和 `manual-publication-regression-evidence.json`。
- 整合验证 PR #193 `9ebdf657` 含 #186–191 的 27 个已审文件，不含 #192/#194；逐 blob 来源核验与独立组合审核通过。[CI](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/34349427487) 及构件已核验：4,947/30 failures/83 errors/20 skipped，111 个唯一失败，对照生产实际消除 163 个、无新增；相关模块及七个映射用例无失败或跳过，45 项发布合同、check、migration drift、正式前后指纹通过。来源 PR 保持打开，未合并或部署；证据为 `runtime/closeout-batch1-integration/ci-comparison.json`。
- M2 自然验收新发现的当地赛时缺失为 PR #194 `51a46c37`，此前生产全量测试未覆盖该形状。本次新增 5 项回归并取得 RED；修复后均通过，完整本机模块 77 项中 73 通过、4 条 Windows raw retention 环境错误。独立审核通过，[候选 CI](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/34427582283) 运行中，不能先计入上述组合修复数。
- 两个 `tmp/` 历史 helper 的 9 条缺失源码失败仍保留；本机、全部本地 refs 路径历史与默认分支 API 路径历史未找到文件，不等于穷尽所有远端/原 PC。恢复线索与限制在 `runtime/closeout-m2-test-ops/missing-helper-recovery-check.json`，未重建假 helper 或删除测试。
- 各候选分别对照同一生产基线，修复数有重叠且尚未合并，不能相加为主线已修复数量；组合候选需要自身 CI。
- 核验输入分别保存在本机 `runtime/fix-reference-parser-tests/ci-comparison.json`、`runtime/fix-test-transaction-boundaries/ci-comparison-r1.json` 和 `runtime/fix-remaining-transaction-tests/delivery.json`；下载的构件均按 GitHub SHA-256 校验，并核对固定候选提交。

## 0078 跟进结果（历史记录）

`fix-0078-recovery-contract` 已完成代码实现与独立测试/复审，交付为 Draft PR #181，未合并或部署。
同环境 Linux/PG16 固定基线 `a88bcbf6` 为 4886 tests、69 failures、258 errors；
最终代码 `966e3455` 为 4925 tests、31 failures、257 errors，0 新增失败、39 个既有失败 ID 消失。
0078 专项 39/39 通过；普通生产代码 rollback 仍按既定策略关闭。
完整结果、仍被不可逆 setup 阻断的旧 PG 场景与测试替身边界见
[验证记录](changes/fix-0078-recovery-contract/validation.md)。下文是原始基线的历史分类与建议。

## 分类与根因

| 类别 | 规模 | 根因 | 典型模块 |
| --- | --- | --- | --- |
| A. macOS 符号链接路径 | 约 100+ 项 | 路径包含判断只 `resolve()` 了一侧，macOS 上 `/var` vs `/private/var` 不匹配；Linux（生产）上是绿的 | `test_historical_*` 各簇、`test_p0_racecard_url_discovery` 多数 |
| B. 契约/摘要漂移 | 约 60+ 项 | main 演进后测试夹具未更新（如 shadow contract scope digest 漂移、写死期望值过期）；多为已冻结的 race_live 旧链 | `test_race_live_*`、`test_realtime_race_results`、`tests_legacy` |
| C. 回滚工具评审上限 | 36 项 | `deploy/verify_rollback_target_migration.py` 把已评审迁移钉死在 0077；0078 随 TRA staging 进 main 后未同步 | `test_single_migration_owner` |
| D. 模块路径 | 18 项 | 测试 patch `runtime.tools.*`，但从 `server/` 运行时 repo 根不在 `sys.path` | `test_race_reference_management_commands` |
| E. compose 断言漂移 | 若干 | 测试写死 compose 文件某行内容，main 改后未同步 | `test_p0_racecard_url_discovery` 部分 |

## 真实运维缺口（优先处理）

类别 C 不只是测试问题：0078 已在生产应用，发布与恢复合同仍停留在0077。
仓库真实策略已明确 `generic_code_rollback_allowed=false`、`reviewed_targets=[]`，
因此普通 rollback 的拒绝是既定策略。模拟允许回滚的测试才会继续碰到迁移上限与假 blob
不一致；不能把它解释为“改上限即可开放生产回滚”。

注意：0078 化不是两行修复——`test_single_migration_owner.py` 的测试线束深度绑定
0076/0077 世代（内联 shell harness、`git-show-0077` 假构件、recovery 参数命名），
正确修法是按 0078 世代重建线束。2026-09-07 曾试探性把上限提升（pin 清单 + allowlist
JSON），失败数不变且失败原因从"0078 ceiling"变为"0076 tail"，已还原，未留半成品。

## 建议处理顺序

1. **C（优先）**：对齐0078发布/恢复合同与测试夹具，验证备份和中断续跑；普通代码回滚保持关闭。
2. **A**：路径比较两侧都 `resolve()`（一处小修，让 Mac 本地可跑全量）。
3. **D/E**：测试补 sys.path 引导；compose 断言改结构化校验。
4. **B（最低）**：race_live 旧链已冻结，建议标记 `expectedFailure` 或随旧链退役清理，
   不逐个追平。

## 长期建议

缺少完整回归使这些失败难以及时暴露。建议最低限度运行一次完整主套件
（哪怕只在合并前本地/容器跑一次并记录结果），否则任何大合并都会继续腐蚀基线。
