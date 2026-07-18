# 准实时赛前 racecard/off time 同步任务

## 0. 探索与方案

- [x] (operations) 从最新 `origin/main@23435897` 创建/快进独立干净 worktree/分支；
  上游仅新增历史发布 evidence 文档，不触及本变更业务代码。
- [x] (application) 审计 RaceEvent、initializer、participant/revision、TRA parser/runner 和前台读取门。
- [x] (integration) 核对官方 Free today/tomorrow racecards、1 RPS 和生产脱敏字段 proof。
- [x] (operations) 固化五份 durable artifacts。
- [x] (integration) 使用 plan-eng-review 完成首次方案审核并关闭 actionable findings；
  同一 reviewer 限定复审结论为 `APPROVED`，无剩余 P0/P1。

## 1. 测试先行

- [x] (integration) 为 live racecard parser 和禁止字段补 RED。
- [x] (application) 为唯一精确赛事匹配、别名年度边界和 blocker 分类补 RED。
- [x] (integration) 为固定 today/tomorrow 网络、registry/secret/host budget 门禁补 RED。
- [x] (application) 为 schema v2 manifest、artifact 路径/权限/无 raw 补 RED。
- [x] (application) 为 v2 dry-run、原子时间写入、初始化、replay 和 rollback 补 RED。
- [x] (integration) 为 PostgreSQL 竞争 manifest 和全事务回滚补 RED。
- [x] (integration) 为 Europe/London/BST/GMT 与 tracking off-time CAS 晋级补 RED。
- [x] (integration) 为 artifact 临时目录/fsync/rename 失败注入和 SHA 绑定补 RED。
- [x] (operations) 把真实 RED 命令、退出码和失败原因写回 `test_cases.md`。

## 2. 实现

- [x] (application) 实现 live Free racecard 严格 parser 和客观字段白名单。
- [x] (application) 实现 Unicode 精确身份归一化和显式 event 批量唯一匹配。
- [x] (integration) 实现 today/tomorrow 受控 transport、host reservation/outcome 和请求元数据。
- [x] (integration) 升级 tracked TRA registry、transport allowlist、Docker copy/SHA 契约。
- [x] (integration) 实现 HostBudget bootstrap、动态状态复用和迟到 outcome CAS 回归。
- [x] (application) 实现 0600 manifest/report/requests artifact 写入。
- [x] (application) 新增 `prepare_race_live_racecards` 管理命令。
- [x] (application) 扩展 initializer schema v2 和 racecard canonical payload。
- [x] (application) 实现同事务时间补齐、初始化、精确 replay 和 verify。
- [x] (application) 实现 Europe/London instant 转换和 status/date/timezone 逐字段 CAS。
- [x] (application) 实现 pre-off 有效 claim 的零 HTTP checkpoint，以及到 off-time
  awaiting 的 owner/claim CAS；stale claim/owner mismatch 零 mutation。
- [x] (integration) 保持 schema v1、results runner、publication gate 与历史链路兼容。
- [x] (operations) 增加 artifact root setting、`.env.example` 和三份 Compose 的 worker-only mount。

## 3. GREEN 与整合

- [x] (integration) 运行新增定向 SQLite 测试。
- [x] (integration) 运行完整准实时与 initializer 回归。
- [x] (integration) 运行临时 PostgreSQL 16 竞争/回滚测试。
- [x] (integration) 运行受影响赛事页、历史 importer/receipt 相邻回归。
- [x] (operations) 运行 Django check、migration drift、Compose config、脚本语法和 diff check。
- [x] (operations) 验证镜像内新 registry SHA，且 web/worker/beat 无 secret mount。
- [x] (operations) 把 GREEN 证据、限制与剩余风险写回 durable artifacts。
- [x] (operations) 在代码 review 前更新 `docs/current_state.md`、`docs/project_status.md`、
  `docs/deploy_runbook.md`，并仅在确有新行为决策时更新 `docs/decisions.md`。

## 4. 独立审核与发布门

- [ ] (integration) 派未参与实现的 reviewer subagent 执行原生只读 uncommitted review。
- [x] (application) 由实现 subagent 修复 artifact 并发误删和占用查询 N+1 两项 findings；
  限定复审复用同一 reviewer 会话。
- [ ] (operations) 记录最终 review fingerprint、approved parent 和 content manifest。
- [ ] (operations) 等待用户在最新成功 review 后授权 commit/push/部署。

## 5. 发布后（不由本次实现授权自动触发）

- [ ] (operations) 部署代码但保持 scheduler/runner/public policy 关闭。
- [ ] (operations) 在生产以显式英国 event IDs 运行受控 prepare（仅 HostBudget 控制面写入）。
- [ ] (operations) 审核 manifest/report/requests SHA 和 blocker。
- [ ] (operations) 对获准 manifest 运行 initializer dry-run/apply/verify。
- [ ] (operations) 另行进入英国 shadow 启动与 10 场/3 重点赛事验收。
