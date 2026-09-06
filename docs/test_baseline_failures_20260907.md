# 测试基线失败排查报告（2026-09-07）

> 背景：M1 全量回归时发现 `origin/main` 基线本身有 235 项失败/错误（全量 4878 项，
> 失败集合与 M1 分支逐项一致，与 M1 变更无关）。仓库没有 CI，失败在 main 上长期累积。
> 本报告记录 2026-09-07 的逐簇取样结论与处理建议，供后续工单使用。

## 分类与根因

| 类别 | 规模 | 根因 | 典型模块 |
| --- | --- | --- | --- |
| A. macOS 符号链接路径 | 约 100+ 项 | 路径包含判断只 `resolve()` 了一侧，macOS 上 `/var` vs `/private/var` 不匹配；Linux（生产）上是绿的 | `test_historical_*` 各簇、`test_p0_racecard_url_discovery` 多数 |
| B. 契约/摘要漂移 | 约 60+ 项 | main 演进后测试夹具未更新（如 shadow contract scope digest 漂移、写死期望值过期）；多为已冻结的 race_live 旧链 | `test_race_live_*`、`test_realtime_race_results`、`tests_legacy` |
| C. 回滚工具评审上限 | 36 项 | `deploy/verify_rollback_target_migration.py` 把已评审迁移钉死在 0077；0078 随 TRA staging 进 main 后未同步 | `test_single_migration_owner` |
| D. 模块路径 | 18 项 | 测试 patch `runtime.tools.*`，但从 `server/` 运行时 repo 根不在 `sys.path` | `test_race_reference_management_commands` |
| E. compose 断言漂移 | 若干 | 测试写死 compose 文件某行内容，main 改后未同步 | `test_p0_racecard_url_discovery` 部分 |

## 真实运维缺口（优先处理）

类别 C 不只是测试问题：0078 已在生产应用，但回滚验证脚本的评审上限停在 0077，
**当前生产回滚脚本会以"超出已评审上限"拒绝工作**。

注意：0078 化不是两行修复——`test_single_migration_owner.py` 的测试线束深度绑定
0076/0077 世代（内联 shell harness、`git-show-0077` 假构件、recovery 参数命名），
正确修法是按 0078 世代重建线束。2026-09-07 曾试探性把上限提升（pin 清单 + allowlist
JSON），失败数不变且失败原因从"0078 ceiling"变为"0076 tail"，已还原，未留半成品。

## 建议处理顺序

1. **C（优先）**：回滚上限 0078 化 + 测试线束按新世代重建；恢复生产回滚能力。
2. **A**：路径比较两侧都 `resolve()`（一处小修，让 Mac 本地可跑全量）。
3. **D/E**：测试补 sys.path 引导；compose 断言改结构化校验。
4. **B（最低）**：race_live 旧链已冻结，建议标记 `expectedFailure` 或随旧链退役清理，
   不逐个追平。

## 长期建议

仓库没有 CI 是 235 项能累积的根因。建议最低限度加一个"主套件全绿"门禁
（哪怕只在合并前本地/容器跑一次并记录结果），否则任何大合并都会继续腐蚀基线。
