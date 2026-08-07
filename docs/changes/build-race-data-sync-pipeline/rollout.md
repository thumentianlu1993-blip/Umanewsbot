# 出马资料、赛果同步与生命周期集成发布方案

## 1. 当前停点与恢复 handoff

- worktree：`.worktrees/build-race-data-sync-pipeline`；branch：`codex/build-race-data-sync-pipeline`；
  parent：`origin/main@54a793089a5a265d608492a6846adb7d040eae00`；实现期间 main 两次前进后均
  fast-forward，当前包含 lifecycle queue route 修复及关闭态部署记录。
- dirty 主工作区未触碰。本轮已完成规划、只读生产探索、测试先行、A 切片本地实现和独立代码审核。
- A 新增测试、应用代码及未应用 migration `0068/0069`；没有生产写、收费 API、credential、
  commit/push/PR/deploy/migrate。
- 同一独立方案 reviewer 首轮提出 5 个 high finding；修订后限定复审为 `VERDICT: APPROVED`。
- 用户已G1 范围确认；当前仅完成 A 的本地关闭态核心，同一独立代码 reviewer 经六轮返修后最终
  `VERDICT: APPROVED`。无 provider 网络 proof，因此除已有 TRA adapter 外，其余 roster entry 保持
  `proof_required`；Ireland 直接 reconciliation marker follow-up 完成并重新 review 前不得进入首发。
- 2026-08-02 快照为 16 个 shadow controls、0 transition、全局 false/off、两个过期 claim、
  race-live 关闭且历史积压 7543；任何执行前重新取证。
- PR #65 已完成生产关闭态部署；R3 遗留 2 条 `default` lifecycle 消息不清理、不重放，必须由后续
  generation bump/CAS 隔离。provider poll 继续使用 `race_live`，不得混入 lifecycle `celery` route。

## 2. 四个独立发布单元

### R-A：racecard observation 与字段 reconciliation

A0 关闭态 schema/code；A1 离线 fixture；A2 六 cohort 各 2–4 场 observation；A3 非 schedule 字段
apply；A4 仅在 C 就绪后启用 schedule-impacting apply。

### R-A2：runner-profile 人工匹配

A2-0 关闭态 link/candidate schema；A2-1 离线候选；A2-2 Admin 确认/改绑/撤销小批；A2-3 验证
manual lock 和未匹配不阻止公开后开放。它不依赖所有 runner 已匹配，也不合并长期 profiles。

### R-B：result observation/revision

B0 关闭态 source-contract/provider-checkpoint schema、adapters/policy，并移除 result projection 对
status 的直接写入；B1 离线调度/phase/迁移；B2 六 cohort 各 2–4 场 observation；B3 单可信来源
official 与显式 provisional revision shadow。B 独立部署期间 public admission 保持关闭，待 C 接入
official-to-lifecycle 后再分别开启 provisional/official public。

### R-C：lifecycle integration

C0 关闭态 reschedule/re-arm/official-evidence integration；C1 只读 manifest；C2 false/off 下原子
control `shadow->enforce` re-arm；C3 cohort 内 schedule auto apply 和旧 task CAS；C4 另获授权打开
global true/enforce 与 result public；验收后该地区 eligible event 自动 enrollment。

不得把四个 PR 合并成一次部署或一次启用。A2 与 B 可在 A 后独立，C 在 A/B 接口稳定后。

## 3. 地区 cohort

首轮 cohort 为香港、JRA、NAR、英国、法国、美国，每个 2–4 场。每个 cohort 单独完成：

```text
observation -> 字段 apply -> result revision/public -> lifecycle enforce
```

通过后可直接扩大到该地区全部符合条件赛事，不等待其他地区。失败只冻结/回滚该 cohort。
Ireland 保留 registry/adapter；线上出现赛事后另做 2–4 场，不阻塞首轮。

符合条件：确定性现有 `RaceEvent` identity、有效 IANA zone、有效 T、登记 route。缺条件只保存
observation，不自动建赛事或进入 enforce。

## 4. 来源与采集门禁

批准 roster：香港 HKJC/TRA Pro；JRA；NAR；英国 TRA Pro/Sporting Life；法国 France Galop/TRA
Pro/ZEturf；美国 Equibase/TRA North America/HRN；后续爱尔兰 HRI/TRA Pro/Sporting Life。

所有来源均可按地区/字段合同自动写入；source class 不形成全局等级。网页来源可直接采集，不把
terms/robots 检查设为发布前置；但不得绕过登录、验证码或访问控制，必须配置 host/path allowlist、
timeout、size、frequency、circuit 和 kill switch。TRA Pro/NA 的生产 credential、配额和联网仍需
独立授权；当前规划阶段 request=0。

## 5. 独立开关

- selector 总开关；provider transport；region/cohort allowlist；
- racecard/result observation；runner 非 schedule apply；schedule apply；
- provisional ingest/public；official ingest/public；
- horse candidate/Admin linking；lifecycle re-arm/enforce；未来 QQ 通知（本阶段固定 false）。

总开关不能隐式提升 control shadow 或绕过 provider/field/phase/cohort 开关。

## 6. 每阶段写前门禁

1. 重验 origin/main、运行镜像、worktree、review fingerprint 和授权范围；
2. 备份/恢复点、migration plan、旧镜像、部署锁、Celery drain 合同通过；
3. 核对 web/worker/beat/race-live flags、queues、active/reserved/scheduled、claims；
4. 冻结 registry/contract、event IDs、field/phase allowlist、request budget 和 artifact SHA；
5. secret 只由受限 runner 读取且不输出；
6. 历史 `race_live` 积压独立分类，不清理、不消费、不计入 smoke。

## 7. 验收门禁

Observation：请求数符合预算；identity/hash/parser 完整；失败可解释；关闭 apply 时业务字段、公开页、
news/QQ 零变化。

Field/result：跨来源冲突不覆盖；legacy authority level 不参与决策；schedule apply 同时 bump 两条
generation/CAS；完整可信结果以 contract + completeness + finality evidence 单源 official；显式
provisional 有公开标签；partial 不公开；B 不直接写 status；cache commit 后一次失效；新闻/QQ 为零。

Multi-provider：每场只有一个父 claim；各 provider checkpoint 独立 due/failure/circuit，A timeout 不
阻止 B；父 next due 取最小值；fallback 成功不停止其他来源 correction；崩溃重投不重复 revision。

Horse link：未匹配 runner 正常公开；确认/改绑/撤销有 actor/reason/audit；自动来源不能覆盖人工锁。

Lifecycle：旧 task 被 CAS 拒绝；global enforce 不提升 shadow；re-arm 原子写 control mode=enforce 且
不执行历史 proposal；全局 off 时无执行、另开全局后 effective enforce；C 才允许 official 经 transition
提前 finished，provisional 不可；来源失败不阻断 T/T+30。

## 8. Promotion/enforce

顺序固定：

```text
false/off read-only prepare
-> exact manifest 授权
-> false/off re-arm apply + verify
-> 停止
-> exact control/cohort 授权
-> true/enforce
```

re-arm manifest 固定 expected mode=shadow/result mode=enforce。事务逐场 CAS，原子改 mode、bump
schedule/claim generation、清 claim、保留历史 proposal 但不执行，按当前事实重算。apply 后全局仍
off；mode/generation 漂移、有效任务/claim、开关不符时零写。相同 manifest 重放 noop。

## 9. 观察指标与容量

- provider request/429/403/timeout/5xx/latency/circuit/schema drift/budget；
- observation matched/unmatched/partial/replay/conflict；字段 applied/replayed/review/rejected；
- result first-attempt、official/provisional 延迟、stale/daily compensation/correction；
- lifecycle stale generation/proposal/applied/next-refresh-null；
- horse candidate pending/confirmed/rebound/conflict；
- cache/page error、news=0、QQ=0、secret leakage=0；raw retention/hold/cleanup 数量。

## 10. 回滚

行为回滚：先关具体 provider/cohort/field/result-public/enforce；确认新 dispatch=0；保留 observation、
revision、field decisions、profile link audit、control/proposal；排队旧 task 由 generation/CAS 零写退出。

代码/migration：additive nullable schema 先部署，旧代码关闭态兼容；数据填充、删除 TRA 名称硬
约束、新 eligibility constraint、legacy authority 读写切换分别迁移。历史 TRA identity 保持
supplemental/eligible=false，旧 authority level 不重写。回退到旧代码前关闭 field/result/lifecycle/
profile apply；新 official identity 在旧代码下只读为 supplemental。schema 反向或整库恢复另授权。

数据纠错：不直接删除 ledger。用 before value、current snapshot 和 CAS 生成逐 event/field/revision/
profile-link reverse manifest，经人工审核回退。只有数据库级损坏才考虑已验证备份恢复。

## 11. 发布后验收与当前停点

验证运行 image/flags、Django/migration、worker/queues/claims、HTTP race pages、exact event DB verifier、
15–30 分钟日志与零重复通知。不能以 HTTP 200 代替 DB/queue/generation 证据。

独立方案审核已经 APPROVED，用户随后明确“G1 范围确认”。当前只完成 A 切片本地实现：SQLite `64/64`、
真实 PostgreSQL `11/11`、相邻 race-live `48/48`，同一独立 reviewer 经六轮审查最终
`VERDICT: APPROVED`。Ireland 直接 reconciliation marker 校验仍是非阻塞 follow-up，因此 Ireland
不进入首发 cohort。A2/B/C、provider 联网 proof、生产数据处理、commit、push、PR、migration 和每个
发布动作均未授权并保持停止。
