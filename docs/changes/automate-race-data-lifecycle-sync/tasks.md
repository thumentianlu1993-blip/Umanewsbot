# 赛事时间、出马表与赛果自动同步任务清单

## 0. 方案与门禁

- [x] (operations) 从最新 `origin/main` 建立独立 worktree，保留共享脏工作区。
- [x] (operations) 只读核对生产 revision、服务、开关、未来赛事覆盖和队列。
- [x] (application) 完成 spec/design/test/rollout 原生方案，不使用 OpenSpec。
- [x] (operations) 完成首轮独立只读工程评审，结论 `REVISE`；修订后由同一 reviewer 限定复审。
- [x] (operations) 清零首轮及后续 actionable findings；同一 reviewer 第 3 轮给出 `VERDICT: APPROVED`。
- [x] (operations) 冻结评审通过的 plan fingerprint；实现不得复用旧 worktree 或旧授权。

## R0：Slice A 扩展、纳管、统一调度与队列隔离

- [ ] (application) 为现有 Slice A roster/flags/reconciler 唯一 owner、legacy 双开冲突和所有配置组合写 RED。
- [ ] (application) 为新增 `data_sync` projection owner 的 acquire/replay/rotate/disenroll/legacy transfer/CAS
  truth table 与旧代码 fail-closed 写 RED。
- [ ] (application) 为稳定 identity 的 region/namespace 唯一约束、contract 升级和历史 adoption 写 RED。
- [ ] (application) 为 99 场完整 census、standing policy、future event enrollment/disenrollment、owner conflict 写 RED。
- [ ] (application) 为 `RaceEventLiveProviderCheckpoint`、父 min-due、claim/generation/CAS 写 RED。
- [ ] (integration) 为 selector 并发、provider 局部失败、DB single-flight owner crash/takeover、host budget 写 RED。
- [ ] (operations) 为 `race_sync_v2` 路由、worker 资源限制、flag-off 三零与 release/rollback/resume 状态机写 RED。
- [ ] (application) 扩展 Slice A schema/roster/flags 和 projection owner enum；不得新增第二 registry、
  reconciler 或业务 flag namespace，历史 `live` 不自动迁移。
- [ ] (application) 实现 manifest-bound enrollment census/apply/disenroll 与 standing policy future discovery。
- [ ] (integration) 实现每分钟 selector、父 claim、provider checkpoint 和持久 single-flight snapshot lease。
- [ ] (operations) 新增专用 worker/queue 与全部默认关闭配置；不得处理 `race_live` 积压。
- [ ] (operations) 同步修改 application/manual/resume/rollback/immutable-control 发布路径的 probe、drain、
  frozen intent、stop/restore 和旧镜像 service catalog。
- [ ] (operations) 运行 targeted/PostgreSQL/Celery/Compose 回归并完成独立代码 review。

## R1：开跑时间与原子 reschedule

- [ ] (application) 为 aware time、IANA/DST、日期-only、manual lock、跨源冲突写 RED。
- [ ] (integration) 为时间变化同时 bump lifecycle/live generation、旧任务零写、缓存 on-commit 写 RED。
- [ ] (integration) 为 schedule×lifecycle/result/checkpoint、racecard×schedule/result 的 PostgreSQL 真并发、
  全局锁序与 abort/retry 写 RED。
- [ ] (integration) 为首批地区时间 adapters 使用离线 fixture 写 parser/identity/schema RED。
- [ ] (application) 扩展 observation/field decision 审计字段，先 nullable migration。
- [ ] (application) 实现 provider-neutral schedule reconciliation 和唯一原子协调器；重构所有逆序
  race-live/lifecycle 写路径及 Slice A observation->event reconciliation 后才接线。
- [ ] (integration) 接入时间 adapters；无时间赛事只做 date-based discovery，不启动 result countdown。
- [ ] (operations) 验证关闭态、shadow coverage、migration/rollback 并完成独立 review。

## R2：出马表与 runner revision

- [ ] (application) 为 participant identity、缺行非退赛、补出/改档/换骑师/manual lock 写 RED。
- [ ] (integration) 为 revision 编号/current/LKG pointer 并发和崩溃重放写 RED。
- [ ] (application) 实现 strict racecard schema、participant/source identity 和逐字段 reconciliation。
- [ ] (application) 实现 append-only racecard revision 与 legacy runner projection。
- [ ] (integration) 接入共享 provider snapshot；未匹配 HorseProfile 不阻塞。
- [ ] (operations) 验证 shadow/apply/public 独立开关、页面和相邻回归，完成独立 review。

## R3：终态赛果 observation 与 revision

- [ ] (application) 为 provider finality、完整 roster、dead heat/nonfinish、partial/DORMANT 写 RED。
- [ ] (application) 为 source label、自动/人工 authority 分离和公共标签写 RED。
- [ ] (application) 为 authority-neutral reported position、可信第三方 `1,1,3` 端到端展示与 adoption 写 RED。
- [ ] (integration) 为 T+3..30 polling、补偿、correction watch、多 provider 冲突写 RED。
- [ ] (application) 迁移 provider-name 特判为 contract eligibility；历史 identity 不自动升级。
- [ ] (application) 实现纯 finality/completeness decision 和 append-only result revision。
- [ ] (application) 新增 `reported_finish_position` 并实现证据约束 migration/legacy 页面 fallback。
- [ ] (integration) 实现 result projection shadow；R4 前不改 status、不公开。
- [ ] (application) 锁定 R3 只创建 immutable unpublished shadow revision；R4 不得重复创建 revision。
- [ ] (operations) 验证现有 scheduled review fallback 完整兼容，完成独立 review。

## R4：生命周期、公开、SLO 与告警

- [ ] (application) 为唯一 result/lifecycle API 的完整 trust-root/claim/enrollment 参数、off/shadow/enforce、
  evidence-driven atomic claim、already-finished、cancel/postpone、shadow promote、事务故障注入与 cache 一致性写 RED。
- [ ] (integration) 为独立 reference 的 upstream availability/detection/publication/blocked-alert 四指标、
  terminal-to-public latency 和 alert 去重写 RED。
- [ ] (application) 实现 `apply_confirmed_result_with_lifecycle()` 单一事务接口；public confirmed 必须为
  lifecycle enforce + exact active membership，由接口在 control row lock 下取得/释放 claim并只 promote 指定
  shadow revision，provisional 不可推进。
- [ ] (application) 实现 official/API/trusted/human/corrected 公开标签和来源展示。
- [ ] (integration) 实现 public verifier、SLO metrics、stale compensation 与 correction watch。
- [ ] (operations) 完成容量、故障注入、kill switch、reverse manifest 和独立 review。
- [ ] (operations) 基于 live disk/约 45GB backups 冻结 artifact quota/high-low water/min-free sizing proof，
  验证低磁盘、quota、cleanup failure 与 hold 膨胀时 request=0/write=0。

## 发布与灰度

- [ ] (operations) 每个 PR 单独冻结 commit、migration、配置、服务、验证和回滚包。
- [ ] (operations) 默认关闭部署和 migration 先通过 G2，真实网络/自动写/公开分别受 G3 精确授权。
- [ ] (operations) shadow 至少 7 天且覆盖至少 10 场终态赛事；输出 coverage/SLO/conflict 报告。
- [ ] (operations) 首发日本重点赛事 2–4 场，event/provider/cohort manifest 精确绑定。
- [ ] (operations) 通过后扩大日本，再依次英国、法国、美国、香港、NAR；单 cohort 可独立冻结/回滚。
- [ ] (operations) 所有公开赛事自动纳管前重新审核来源覆盖、容量、成本和异常率。
- [ ] (operations) 更新 `docs/current_state.md`、`docs/decisions.md`、`docs/project_status.md`；逐项 review
  `docs/project_overview.md`、`docs/deploy_runbook.md`、`docs/deploy_production.md`、`docs/rollback_guide.md`、
  `docs/backup_recovery.md`，无需改动者也记录“reviewed/no update required”，并补 release evidence。
