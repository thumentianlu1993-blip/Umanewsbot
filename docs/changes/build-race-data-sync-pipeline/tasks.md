# 出马资料、赛果同步与生命周期集成任务

规划已完成并获用户“G1 范围确认”。当前仅 A 切片完成测试先行、实现和独立代码审核；A2/B/C 与发布仍未开始。

## 0. 方案门禁

- [x] (operations) 从已验证 `origin/main` 建立独立干净 worktree/branch，不触碰 dirty 主工作区。
- [x] (operations) 只读盘点仓库与生产 lifecycle/race-live/proof/queue 状态。
- [x] (integration) 调研目标地区公开来源并编写覆盖矩阵。
- [x] (operations) 编写 spec/design/test_cases/tasks/rollout 并完成用户 grilling。
- [x] (operations) 同一独立 reviewer 审核与限定复审完成，最终 `VERDICT: APPROVED`。
- [x] (operations) 汇报方案、RED、风险/回滚并取得用户“G1 范围确认”。

## A. `sync-racecards-and-race-schedules`

- [x] (integration) 先写 observation/schema/identity/provider-budget RED。
- [x] (application) 先写 runner merge、字段冲突/manual lock/schedule 禁入 RED。
- [x] (operations) 先写 raw retention、secret redaction、flag-off RED。
- [x] (application) 扩展 observation/field audit models；新 reconciliation 不读取 `authority_level`，
  并完成 nullable additive migration。
- [x] (application) 在独立代码 review 后补齐 decision enum/constraint 与 Admin 的 legacy authority
  标注、筛选和完整 provenance 展示是否仍需补强。
- [x] (integration) 实现 versioned roster、strict schema 与 adapter 状态；TRA 为 implemented，其余在
  未获逐来源联网 proof 前保持 `proof_required`，不伪造 parser 已完成。
- [x] (application) 将 TRA 专用 apply 接入 provider-neutral reconciliation/projection。
- [x] (operations) 实现默认关闭的 provider/region/field flags 与 90 天 raw cleanup；未新增 Beat。
- [x] (operations) GREEN、PostgreSQL 并发、迁移/关闭态验证、独立代码 review、文档回写。

## A2. `match-race-runners-to-horse-profiles`

- [ ] (application) 先写候选、未匹配公开、确认/改绑/撤销、manual lock、并发 RED。
- [ ] (application) 设计并迁移 runner-profile link/candidate/audit，复用既有身份治理模型。
- [ ] (application) 实现候选服务与 Admin 审核；不得自动合并两个长期 profile。
- [ ] (application) 验证权限、CAS、人工锁、未匹配 runner/racecard/result 回归。
- [ ] (operations) GREEN、迁移/回滚、独立代码 review、文档回写。

## B. `ingest-race-results-by-authority`

- [ ] (integration) 先写 T+3 至 24h 调度、stale/daily compensation、失败 RED。
- [ ] (application) 先写单可信来源 official、显式 provisional、partial/conflict/correction RED。
- [ ] (application) 先写 B 不改 status、public admission 关闭态、零新闻/QQ RED。
- [ ] (integration) 先写多 provider checkpoint、partial crash/replay、host budget 独立 RED。
- [ ] (application) 先写 source identity contract/constraint forward/backward migration RED。
- [ ] (application) 新增 result contract/finality eligibility，移除 TRA provider-name 硬约束但保留
  fail-closed DB constraint；历史 identities 不自动升级。
- [ ] (integration) 新增无 claim/mode 的 provider checkpoint 子表，复用唯一 tracking claim/worker，
  实现 provider-neutral adapters、execution plan 与父 min-due policy。
- [ ] (application) 复用 observation/revision/projection 完成 reconciliation；移除 provisional/official
  projection 对 `RaceEvent.status` 的直接写入，C 前 public admission 保持关闭。
- [ ] (operations) GREEN、PostgreSQL 多来源并发、关闭态验证、独立代码 review、文档回写。

## C. `integrate-race-data-with-lifecycle`

- [ ] (application) 先写原子 schedule、双 generation、终态回退审核、shadow->enforce re-arm RED。
- [ ] (integration) 先写真 PostgreSQL 旧 task CAS、锁序与自动 enrollment RED。
- [ ] (operations) 先写 strict manifest/false-off/replay/rollback RED。
- [ ] (application) 实现统一 schedule transaction 与 lifecycle/live invalidation。
- [ ] (application) 实现 re-arm/recompute prepare/apply/verify；事务内 CAS `shadow->enforce`、bump、
  清 claim、重算，manifest 固定 before/after mode；不支持旧 proposal 直接 apply。
- [ ] (integration) 接入 B official evidence 到既有 lifecycle transition；provisional 不推进；接入
  地区验收后的 eligible event enrollment。
- [ ] (application) 接入 on-commit cache，无新闻/QQ side effect。
- [ ] (operations) GREEN、并发/rollback 演练、独立代码 review、runbook/状态文档回写。

## 发布门禁（每个 PR 独立）

- [ ] (operations) review 后另获 commit/push/Draft PR 授权。
- [ ] (operations) 关闭态部署、备份、migration、服务恢复与验收分别授权。
- [ ] (operations) provider 联网/凭据、observation、字段 apply、结果公开分别授权。
- [ ] (operations) 六 cohort 每区 exact 2–4 场，验收后该 cohort 全量扩展另授权。
- [ ] (operations) re-arm/control promotion 与 true/enforce 分别授权。
- [ ] (operations) 发布后 evidence-only closure 复用首次代码 reviewer。
