# 测试基线失败排查报告（2026-09-07）

> 背景：M1 全量回归时发现 `origin/main` 基线本身有 235 项失败/错误（全量 4878 项，
> 失败集合与 M1 分支逐项一致，与 M1 变更无关）。当时没有完整 stable 回归 CI；已有的两条专项 workflow 不覆盖该基线。
> 本报告记录 2026-09-07 的逐簇取样结论与处理建议，供后续工单使用。

## 2026-09-09 当前基线与收口边界

- 0078 发布恢复合同已合并并上线；PR #184 的最新生产候选 `69955960` 通过 45 项 Linux/PostgreSQL 16 发布专项，当前是完整 0078、全图空迁移计划。下节“Draft PR #181，未部署”只描述当时进度，不能再列为现行阻塞；普通代码 rollback 仍按既定策略关闭。
- 最新证据：[CI run 34319906713](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/34319906713)，4,943 tests、31 failures、257 errors、20 skipped，274 个唯一失败 ID；与前生产候选 `31bf6095` 集合相同，且无相对同环境历史基线新增失败。原“235 项”和下表 Mac 分类是旧基线，不能代替此次 Linux 结果。
- 初步按异常末行归组，105 条记录涉及事务隔离级别设置时机、31 条涉及 `runtime` 导入、28 条涉及不可逆 0078 的测试准备，另有旧发布合同摘要、nullable outer join 锁和缺失旧工具路径等；这些是失败记录数，可能含同一测试的子测试，不等同于独立根因数量或生产缺陷数量。完整输入保留在本机 `runtime/fix-release-discovery/pr184-stable-candidate.zip`。
- 当前处理顺序：按共同根因复现 → 判断应用缺陷/测试准备/过期合同 → 最小修复与有效回归 → 同环境全量核对 → 独立 review。先处理可跨模块消除失败的导入和测试基础，不通过放宽断言、批量 expectedFailure 或跳过整套测试制造绿色。实际任务状态只维护在 [roadmap 当前收口节](future_work_roadmap.md)，本报告保留诊断依据。

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
