# 测试基线失败排查报告（2026-09-07）

> 背景：M1 全量回归时发现 `origin/main` 基线本身有 235 项失败/错误（全量 4878 项，
> 失败集合与 M1 分支逐项一致，与 M1 变更无关）。当时没有完整 stable 回归 CI；已有的两条专项 workflow 不覆盖该基线。
> 本报告记录 2026-09-07 的逐簇取样结论与处理建议，供后续工单使用。

## 0078 跟进结果

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
