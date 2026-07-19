# event 924 暂定赛果单赛事公开灰度任务

## 方案与门禁

- [x] (operations) 确认干净 worktree、最新 `origin/main` 和独立分支。
- [x] (operations) 只读核对 event 924 生产 shadow、policy、allowlist、source、
  observation、revision、前台读取和 scheduler。
- [x] (integration) 人工交叉核对 TRA 1–7 顺序与 Racing Post、Sporting Life 客观赛果；
  明确它们不是自动生产 API 或 official authority。
- [x] (application) 完成首轮方案审核并取得 4 个 high、2 个 medium finding。
- [x] (application) 复用同一方案 reviewer 完成限定复审并关闭 P0/P1 finding；
  `VERDICT: APPROVED`。

## 测试先行

- [x] (operations) 添加安全 bundle prepare、manifest parser、命令参数和 exact pre-state
  RED。
- [x] (integration) 添加已存 shadow operator promotion、唯一 locked admission core、幂等、
  tracking provider 字段不变和无网络 RED。
- [x] (integration) 添加 allowlist route digest、manual official receipt、match/conflict/
  unavailable incident 处理 RED。
- [x] (application) 添加 projection 精确 fallback/provenance、event finished 和
  phase-aware hero RED。
- [x] (integration) 添加 shared public policy 下第二个 shadow initializer、missing event
  policy fail-closed RED。
- [x] (operations) 添加 disable/restore、scheduler/allowlist universe 和脱敏输出 RED。
- [x] (integration) 在 PostgreSQL 取得并保存任意子步骤失败整体回滚、runner/operator
  无死锁和并发 CAS RED。
- [x] (integration) 首次代码 review 后为 event 924 receipt 硬限、真实邮件
  SENT/FAILED/retry 和 shared dry-run planner 分别取得真实 RED。
- [x] (integration) 为剩余两项直接 P1 取得真实 RED：incident 跨 receipt 去重、SMTP 前
  durable intent/probe/operation 可见、主事务晚期写入失败和 commit 失败均不得发信。

## 实现

- [x] (application) 添加 `0046` migration、allowlist/incident route contract 与人工责任
  时限字段。
- [x] (operations) 实现安全 publication transition bundle prepare、严格 manifest loader
  和稳定 summary。
- [x] (integration) 抽取唯一 locked admission core，实现 operator outer-transaction
  orchestration；不创建 claim、不调用 checkpoint、不改 provider timing。
- [x] (integration) 实现 allowlist v1->v2 route digest CAS、shared/event policy 独立匹配
  和 missing event policy fail closed。
- [x] (application) 实现 current racecard 客观字段 fallback 和 provisional event finished
  状态，并保存字段级 provenance。
- [x] (application) 修正 provisional hero 的“冠军 · 暂定”语义。
- [x] (application) 实现 `transition_race_live_publication` dry-run/apply/verify 命令。
- [x] (operations) 实现 event 精确 disable/restore manifest、稳定 JSON 输出和幂等
  operation log。
- [x] (integration) 实现受审 BHA manual route registry、offline receipt prepare/apply、
  match resolve、conflict 原子 disable 和 unavailable alert/open。
- [x] (integration) 按首次 code review finding 将 manual receipt 硬限 event 924；
  unavailable 接入真实邮件并实现失败重试/成功去重；dry-run/apply 共用 locked planner。
- [x] (integration) 将 unavailable 告警改为 incident 级稳定去重和两阶段 durable
  outbox：主事务原子提交 probe/receipt operation/QUEUED intent，提交后才投递，
  delivery 写 SENT/FAILED；跨 receipt 继续推进 probe 但不重复发信。
- [x] (operations) 更新发布前完整审核范围内的 current state/project status/runbook/
  decisions；不扩大自动 official adapter 范围。

## 验证与审核

- [x] (application) 运行聚焦 SQLite 测试、Django check、migration drift。
- [x] (integration) 运行 migration 往返和真实 PostgreSQL 原子性/并发/无死锁测试。
- [x] (operations) 验证三份 Compose、worker route/resource、scheduler 默认 false。
- [x] (application) 未参与实现的 reviewer 已在 session
  `019f76c2-78bd-7ed3-9107-a7b1c2a7aa4e` 执行首次完整 review，结论 `REVISE`。
- [x] (application) 修复首次 review 的 2 项 P1 和 1 项 P2，并完成直接测试/文档验证。
- [x] (integration) 修复随后两项直接 P1，并完成 SQLite `226` 项、PostgreSQL 新增
  `2/2` 与既有 `22/22`、静态与 Compose 验证。
- [ ] (application) 复用同一 reviewer session 完成本轮全部 actionable finding 的限定
  复审。
- [ ] (operations) 冻结完整 fingerprint、approved parent 和 content manifest hash。

## 发布（只在最新成功 review 后取得精确用户授权）

- [ ] (operations) 核对生产 checkout、镜像、当前 event 924 baseline 和无其他 event 扩张。
- [ ] (operations) 创建并验证发布前数据库备份。
- [ ] (operations) 部署受审冻结版本，保持 scheduler=false。
- [ ] (operations) 生成 event 924 精确 promotion/disable/restore bundle，审核 SHA 和权限。
- [ ] (operations) promotion dry-run -> apply -> verify。
- [ ] (application) 验收详情页/日历的暂定标识、顺序、event finished 和缺失字段展示。
- [ ] (operations) 在同一维护窗口人工执行 BHA 首次 probe：match 关闭 incident；
  conflict 原子 disable；unavailable 保持 open/alert/provisional。
- [ ] (operations) 验收 publication/legacy result/incident/claim/provider timing/queue/
  health/resource。
- [ ] (operations) 演练 event 924 disable 并决定按授权恢复 provisional 或保持隐藏。
- [ ] (operations) 按 evidence-only allowlist 追加生产事实，复用同一代码 reviewer 审核。

## 后续独立变更

- [ ] (operations) 实现 overdue incident 自动探针/告警与 T+24h/T+72h/T+7d 修订闭环。
- [ ] (integration) 在条款与许可允许时，为 BHA 建立自动 official adapter；当前
  `manual_browser_only` 路线不得自动化。
- [ ] (integration) 将已验证的 manual official observation 晋级为正式赛果，需要单独
  `official_public` change 和审核。
- [ ] (integration) 在连续两个真实窗口达标后，才提出第二个 event 或 scheduler 灰度。
