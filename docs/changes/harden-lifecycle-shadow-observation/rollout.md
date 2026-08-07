# Lifecycle shadow 观察加固发布方案

## 1. 当前基线

- 开发基线：`origin/main@ba9c0f00bc435c806864fa7a27f00dce545f1efc`。
- 独立 worktree：`.worktrees/harden-lifecycle-shadow-observation`。
- 生产应用：`main@d5ae1d7e` 的隔离 release，web/worker/Beat 当前统一 `true/shadow`，
  race-live worker 未启动。
- 现有 16 controls 全部 shadow；截至 `2026-08-08 02:04 +08:00` 为
  `proposal=16 / applied=0 / active_claim=0`。
- 今日三场自然观察边界尚未到达，因此当前无新 transition 是预期结果。
- 主工作区有大量其他任务未提交改动，本 change 不读取为实现基线、不修改、不清理。

## 2. 并行边界

- 本地文档、测试与实现可和其他任务并行，但文件重叠必须停下协调。
- 关闭态部署、服务重建、Celery drain、flag 变更和生产观察不得与其他数据库写批次、部署、
  migration 或服务重建并发。
- `default=2`、`race_live=7543` 保持原样；不 purge、不消费、不启动 race-live。

## 3. 发布阶段

### R0：关闭态部署

1. 重开生产 HEAD、运行容器、共享锁、队列、active/reserved、磁盘和备份条件。
2. R0 前只读确认 canonical `/opt/umanewsbot/.env` 已为唯一键 `false/off`；从精确 merge commit
   建隔离 release，并只从该 canonical 文件复制 mode-600 `.env`。旧 active release 的
   `true/shadow` 文件不作为新 release 输入。
3. 使用标准共享部署锁、单一 release task 和 web healthy
   门禁部署。
4. 新代码已落地后，一致性脚本确认 web/worker/Beat 同 project/release/image/commit、`false/off`。
5. scanner smoke 必须零 claim/dispatch；公开状态和 transitions 不变。

### R1：恢复 shadow

1. 单独取得针对精确 16 event IDs、manifest、revision 和观察窗口的授权。
2. 从既有 16 controls 冻结尚未到 T、覆盖日本和英国的 2–4 场精确清单；样本不足即 NO-GO。
3. 确认没有其他生产写入/部署，调用本次 R0 已部署的专用 mode switch；脚本自行取得共享锁，按 Beat-last
   顺序切换双 env、重建并全量核验。
4. 不手工 scanner，等待 Beat 自然执行。错过边界时重新冻结未来清单，不补采冒充自然证据。

### R2：24 小时内的自然观察

- 观察 R1 冻结的 2–4 场未来样本；每次 T 与 T+30 后保存数据库、宿主全量容器、队列和
  日志快照。`2026-08-08` 的 events `86/943/942` 只作为本 change 实现前的现网观察，不自动
  计入修复后 enforce 证据。
- GO：proposal 正确、applied=0、公开状态不变、failures=0、claims 清空、无 mismatch 日志。
- NO-GO：立即统一回到 `false/off`；保留全部审计，不删除 proposal，不反改赛事状态。

### R3：enforce

本 change 不执行。只有 R2 通过后另立 enforce change，限定 2–4 场人工核对赛事，重新完成
spec/design、review、用户确认和发布授权。

## 4. 回滚

- 运行异常首先统一 `false/off`，在共享锁内从当前隔离 release 重建三服务并用一致性脚本验证。
- 代码回滚只回到部署前冻结镜像；无 schema 回滚。
- 已产生 proposal 和准确的 success 统计保留；不删 control/transition。
- 若旧 checkout 再次重建服务，视为生产协调事故：先停 lifecycle、保留容器 label/flags/日志
  证据，再从 active release 统一恢复；不得用旧目录继续修补。

## 5. 证据

发布证据写入 `release_report.md`，并追加：

- `docs/current_state.md`
- `docs/project_status.md`
- `docs/deploy_runbook.md`
- `docs/decisions.md`（仅实际发生且必要的新决策）

证据必须记录精确 SHA、image、release directory、备份、flags、event IDs、T/T+30、proposal/
applied/failure/claim 计数、队列、HTTP 和异常；未知项写 unknown，不猜测成功。
