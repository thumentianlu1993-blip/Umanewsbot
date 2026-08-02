# 单一迁移执行者修复任务

实现与测试已完成（聚焦 87/87、相邻回归 11/11）。子代理仍不得 commit、push、PR、
部署、迁移或连接生产；发布相关任务保持未勾选，等待发布授权。

## 测试

- [x] (operations) 冻结最新 `origin/main`、工作树状态和设计 fingerprint，确认实现授权范围。
- [x] (operations) 由测试 subagent 新建 `stable.test_single_migration_owner`，覆盖唯一 owner、
  release 顺序、健康等待、锁、race-live 状态保持、标准/lowcost deploy 和两类 rollback。
- [x] (operations) 运行聚焦测试取得真实 RED，保存失败用例、命令、exit 和能力缺口。
- [x] (operations) 补充 migration/release/health 各失败点的 fail-closed harness。

## 实现

- [x] (operations) 新增唯一容器内 `deploy/docker/run-release-tasks.sh`。
- [x] (operations) 新增 allowlist 且 fail-closed 的宿主 `deploy/run_release_tasks.sh`。
- [x] (operations) 新增 host-local 排他部署锁和有界 web healthy 等待脚本。
- [x] (operations) 新增共享 application release orchestration，固定停服、release、健康和恢复顺序。
- [x] (operations) 保存并恢复 race_live_worker 原始运行态，migration 窗口内停止全部应用 worker。
- [x] (operations) 扩展 Celery drain，要求本次冻结的普通/race-live worker node 全部响应且
  active/reserved/active-confirm 为空。
- [x] (operations) 新增 pre-contract image rollback bridge，并让通用 rollback 在停服前校验
  `release_contract_v1`。
- [x] (operations) 从 `start-web.sh` 移除 migrate/collectstatic，保留依赖等待、seed 和 Gunicorn。
- [x] (operations) 修改标准/lowcost deploy 与 rollback，复用唯一 release orchestration。
- [x] (operations) 更新既有环境手工恢复、部署、失败恢复和 rollback 文档，不改业务开关。

## 验证

- [x] (operations) 运行聚焦测试并取得 GREEN，核对 RED 原因确由目标能力修复。
- [x] (operations) 运行真实 shell fake harness 的标准/lowcost deploy、rollback 和失败矩阵。
- [x] (operations) 验证 deploy/rollback/手工 release 锁竞争者不能进入或释放赢家锁。
- [x] (operations) 运行 shell syntax、两份 Compose config、Django check、migration drift、
  `git diff --check`。
- [x] (operations) 运行 historical runner/deploy 相邻回归。
- [ ] (operations) 在隔离、非生产 Compose 中验证一次正常 release、一次重放和一次失败恢复。
- [x] (operations) 主线程核对变更仅含测试、部署脚本和必要文档，没有 Django migration 或业务代码。

## review

- [x] (operations) 冻结 content manifest 与 fingerprint。
- [x] (operations) 由未参与实现的独立 reviewer 执行 Codex 原生只读代码 review，重点检查单一
  owner、并发、失败边界、rollback、greenfield 非目标和测试真实性。
- [x] (operations) 有 finding 时先补真实 RED，再修复，并复用同一 reviewer 会话复审。
- [ ] (operations) review `APPROVED` 后重新冻结 fingerprint，停止并等待用户发布授权。

## 发布

- [ ] (operations) 取得针对当前 fingerprint 的 commit/push/Draft PR 授权。
- [ ] (operations) PR 合并前核对 CI、review 和最新 `origin/main`；合并需独立授权。
- [ ] (operations) 部署前重新只读核对生产状态、迁移计划、开关、队列、锁、磁盘和健康。
- [ ] (operations) 创建并校验数据库备份，冻结旧 HEAD/image/env filtered hash。
- [ ] (operations) 取得当前版本生产部署与 migration 授权。
- [ ] (operations) 按 runbook 执行单一 release task 部署，禁止并发其他生产写入。
- [ ] (operations) 验证 migration owner、服务启动时序、Django、healthz、Celery、日志和开关。
- [ ] (operations) 保存生产证据；只有另行授权后才恢复后续 lifecycle/B0.1 工作。
