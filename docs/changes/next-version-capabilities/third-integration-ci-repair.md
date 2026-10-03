# 第三组合 CI：H01 观察证据被后续采样覆盖

2026-10-04，北京时间。仅测试辅助器修复，生产 reader、SQL、超时、权限和回滚流程不变。根 AGENTS.md 为唯一人工门禁；未合并、部署或操作生产。

## 实际失败

PR237 固定 `4e8993c818de459df3fe89f80f6f386badf47e13` 的正常 PR CI `37153715101` 已执行 6458 个唯一测试、47 批，所有批次 lifecycle=complete：1 failure、0 error、10 个原许可 skip。失败为 `H01CountPostgresTests.test_cli_deadline_stops_active_backend`，不是新增纯核心测试。verify-execution、独立 collection、镜像上传未执行，故没有正式交付通过证据。

`batch-006.log` 的首次 `H01_PG_INITIAL` 已记录同 PID 的 `locks_before=1`。`pg_stat_activity` 与随后 `pg_locks` 是两次查询；退出期间后一次可返回零。观察器每轮覆盖 `locks_before`，最终 `_check_observation` 读取零而失败。该失败不能用一次重跑成功抹去。

## 修正与真实 RED/GREEN

保留首次同时具有正确身份和正持锁数的活动收据，此后零采样不覆盖 `locks_before/active_at`。身份不匹配或只有零采样不能发初始正向收据。后续消失、释放后锁零、原 deadline、近 kill 屏障和五个真实 PG 方法的断言保持。

同文件新增四项确定性离线反例：先正后零、仅零、先零后正、错误身份。修改辅助器前四项均因目标行为 assertion FAIL（0 error）；最小修复后相同四项 PASS（0 failure/error/skip）。本地运行从原文件提取未改写的 observer 函数与测试类 AST，禁止导入 Django 或建立 libpq 连接；这是协议单元证据，不能代替实际 PG 运行。源码、runner、原始 RED/GREEN log 均保存在专属 runtime 并绑定哈希，未用最终源码冒充 RED 时源码。

工作流合同检查 PASS，合同单测 4 PASS，diff check PASS。现有 `horse_target_inventory` 已映射整个 `stable.test_h01_count_postgres` 模块，新增类随原模块选择，不新增或缩减共享规则、profile、skip。原 R 审核固定提交后，在新候选正常隔离 CI 补真实 PG 和完整候选回归；当前未复验 PG、未宣称新 CI 成功。

证据目录：`/Users/mentianlu/.codex/runtime/h01-observer-race-20261004/`，入口 `evidence.json`。失败工件原件：`/Users/mentianlu/.codex/runtime/third-integration-evidence/ci37153715101-artifact/`；GitHub artifact `11285866161`、`impact-37153715101-1`。回滚只撤销本测试辅助器与新增回归，不涉及生产状态。
