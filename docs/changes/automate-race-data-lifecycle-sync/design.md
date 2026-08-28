# 赛事时间、出马表与赛果自动同步设计

## 1. 设计结论

本功能复用现有赛事总账、race-live observation/revision、字段审计、lifecycle 与定时审核链路，新增
统一的 provider-neutral 调度和协调层。它不创建新的赛事总账、第二套结果表或第三套生命周期状态机。

主要决定：

1. 一个 Beat selector + 每场 `next_poll_at`，取代逐赛事固定 cron；
2. 现有 race-data Slice A 是唯一 provider roster、合同校验、observation 与字段 reconciliation 内核；
   `race_sync_v2` 只命名新队列/worker，不建立第二套业务 flag 或 writer；
3. 来源优先级固定为 Racing API（`licensed_api`）> 官网/官方导入（`official_operator`）> 可信第三方
   （`trusted_publisher`）；三类都可无人审核自动采用，冲突按等级、时间和稳定 provider key 确定性仲裁；
4. 来源类别、结果 finality、人工审核方式分字段表达，不再共用一个含糊 authority；
5. 时间变更、出马表、赛果与 lifecycle 通过 generation/CAS 汇合，任何旧任务零写退出；
6. dry-run 和最终生产确认后可在同一隔离 release 中直接上线；future discovery、network/time/racecard、
   lifecycle、result/public/correction 仍用独立开关顺序启用，以便每一步自动验收和止损，但不要求逐场确认、
   固定 7 天 shadow 或逐地区人工批准。

## 2. 现有能力复用审计

| 现有能力 | 复用方式 | 当前缺口 |
|---|---|---|
| `RaceEvent` / `RaceEventRunner` / `RaceEventResult` | canonical 公开投影 | 时间覆盖不足；runner 为空 |
| `RaceEventLiveTracking` | 每场唯一 tracking、claim、`next_poll_at` | 单 provider checkpoint 不足 |
| `RaceEventProjectionControl` | revision 编号与 current/LKG pointer | 需要统一 source/finality 决策 |
| `RaceResultSourceIdentity` | provider external ID 绑定 | 当前含 TRA provider-name 特判，需迁移为合同资格 |
| `RaceEventParticipant` | event-scoped 稳定参赛身份 | racecard 覆盖和跨 provider identity 不完整 |
| `RaceResultObservation` | 统一承载 time/racecard/result observation | 名称历史遗留，但无需另建 observation 表 |
| `RaceEventRevision` | racecard/result append-only revision | 需要 source label、finality 与 correction 合同 |
| `RaceEventFieldAuthority/Change` | 赛事字段 before/after 审计；`FieldChange` 已有 observation、parser/contract/task/generation/decision | authority 与 coordinator 的锁序、source/finality 规则尚需闭合 |
| `RaceEventLifecycleControl/Transition` | 时间状态推进与 generation/CAS | 时间修正与 result evidence 尚未统一协调 |
| `race_live_racecard_sync.py` | parser、TRA racecard、匹配基础 | 当前 provider 专用且生产关闭 |
| `race_live_runner.py` | region snapshot cache、结果 parser、poll runner | 只面向旧 `race_live` queue/策略 |
| `scheduled_race_result_review.py` | 72h 补偿、bundle、人工 apply fallback | 不是 30 分钟自动写入链 |
| P0 官方 URL discovery | 发现候选 URL | 每日两次且不产生完整 racecard |

实现前先做 schema-delta audit；现有字段能表达的内容不重复建表。

### 2.1 Slice A 精确 delta 与唯一 owner

| 主干能力/字段 | 最终决定 | 本方案增量 |
|---|---|---|
| `RaceDataSyncFlags` / `RACE_DATA_SYNC_*` | 保留，作为 canonical 字段 apply admission | 扩展 scheduler/network/data-kind/public/correction 子开关；不新增 `RACE_SYNC_V2_*` 业务开关 |
| `RaceDataProviderRoster`、contract digest/validator | 保留并扩展，唯一 registry facade | 增 time/result route、identity namespace、terminal marker、validity/request policy；不建第二 registry |
| `normalize_racecard_observation()` | 保留，作为严格 racecard normalizer | 抽取共享 envelope，再添加 strict time/result normalizer |
| `_reconcile_racecard_observation_atomic()` | 保留，作为 racecard field writer | `allow_schedule_apply=True` 继续拒绝；schedule 只能交给本方案唯一 coordinator |
| `RaceResultObservation` | 保留，唯一 observation ledger | 已有 observed/source-updated、parser、raw/normalized SHA、artifact/size/retention 等；只补显式 `data_kind`、registry/contract/task/identity/finality decision 等当前确实缺失字段 |
| `RaceEventFieldChange` | 保留，唯一 field decision ledger | observation、source class/time、parser、raw/normalized、registry/contract、task、decision、generation/mode/applied/reason 已存在，不重复加列 |
| `cleanup_expired_race_data_raw_payloads()` | 保留 | 增加容量 admission、quota/hold 统计和高低水位；不新建清理器 |
| `RaceEventProjectionWriteOwner` | 增 `DATA_SYNC="data_sync"`，作为新 writer 的唯一持久 owner | legacy `LIVE="live"` 不复用、不自动迁移；additive enum/code migration 后旧代码对未知 owner 必须 fail closed |
| `RACE_LIVE_*` writer | legacy only | 新 enrollment 不派发 legacy 队列；迁移期若 owner 为 `live` 则阻断，不能双写 |

配置组合的唯一性由一张 admission truth table 和测试锁定：只有
`RACE_DATA_SYNC_ENABLED ∧ provider ∧ region ∧ field/data_kind ∧ 对应 apply flag ∧ enrollment membership`
全部满足且 `write_owner=data_sync` 时 Slice A/协调器才可写。旧 `RACE_LIVE_*` 开关不能为新 cohort 授权；任何同时开启或 owner
不唯一的组合都返回 `writer_owner_conflict`，canonical writer 数必须为 0 或 1，绝不能为 2。

## 3. 总体数据流

```text
Celery Beat: every minute
  -> select_due_race_sync_v2_task (ordinary queue, short task)
      -> lock/claim RaceEventLiveTracking
      -> freeze due-provider plan + generation + attempt token
      -> sync_race_event_provider_task (race_sync_v2)

extended Slice A provider roster/contract
  -> bounded transport + provider/region shared snapshot
  -> immutable raw artifact + RaceResultObservation
  -> strict parser / normalization
  -> identity and completeness gate
  -> reconciliation decision
      -> RaceEventFieldChange + racecard revision
      -> result revision
      -> needs_review incident
  -> atomic projection coordinator
      -> RaceEvent / Runner / Result
      -> lifecycle + live reschedule
  -> transaction.on_commit cache invalidation
  -> public verifier + metrics
```

transport 不写业务字段；parser 不访问数据库；decision service 不联网；projection coordinator 不发外部通知。

## 4. Slice A provider roster 扩展

唯一 roster/registry facade 的每条 route 使用确定性 JSON，至少包含：

```json
{
  "key": "jra-results-v1",
  "provider": "jra",
  "region": "japan",
  "identity_namespaces": ["jra_race_id"],
  "data_kinds": ["race_time", "racecard", "results"],
  "source_label": "official",
  "parser": "jra_results_v1",
  "terminal_markers": ["OFFICIAL"],
  "allowed_hosts": ["example.invalid"],
  "allowed_path_prefixes": ["/"],
  "request_budget": 20,
  "minimum_interval_seconds": 2,
  "automation_allowed": true,
  "proof_digest": "<64hex>",
  "contract_version": "1",
  "valid_until": "<aware datetime>"
}
```

示例中的主机只是 schema 说明，真实 registry 必须使用逐来源审核值。route validator 要求：

- key、provider、region、namespace、parser、data kind 唯一；
- method/host/path/redirect/size/timeouts 全量 allowlist；
- terminal marker 只能由对应 parser 解释；
- `automation_allowed`、proof、contract 和有效期全部满足；
- registry raw SHA 与运行配置绑定；
- credential 只由专用 worker 在内存读取，不写 artifact、日志或数据库。

首轮候选路由来自现有仓库 adapter：JRA/NAR/HKJC、The Racing API、Sporting Life、France Galop/
ZEturf、Equibase/HRN。每个地区必须重新完成 schema、身份、终态和网络许可 proof；旧成功记录不是
永久授权。

## 5. 数据模型增量

### 5.1 `RaceEventLiveProviderCheckpoint`

新增 tracking 子表，唯一键 `(tracking, source_key, data_kind)`：

- `next_poll_at`、`last_attempt_at`、`last_success_at`；
- `data_kind`、`last_observation_hash`、`last_source_updated_at`；
- `consecutive_failures`、`circuit_reason`、`stale_at`；
- `contract_digest`、`registry_digest`；
- `lock_version`。

它没有独立 enable/mode/claim/token，不由 selector 单独扫描。父 tracking 仍是唯一 claim；父
`next_poll_at` 等于所有有效 checkpoint 的最小 due。

tracking 不新增状态值，迁移/运行表固定为：

| canonical `RaceEventLiveState` | 合法后继 | selector/UI 派生 phase |
|---|---|---|
| `scheduled` | `racecard_ready`, `awaiting_result` | 无时间时 `time_pending`；否则 `prerace_tracking` |
| `racecard_ready` | `awaiting_result` | `prerace_tracking` |
| `awaiting_result` | `provisional_result`, `official_result` | `awaiting_result` |
| `provisional_result` | `official_result`, `corrected_result` | `awaiting_result` |
| `official_result` | `corrected_result` | 有 due checkpoint 时 `correction_watch`，否则 `closed` |
| `corrected_result` | 无自动回退 | 有 due checkpoint 时 `correction_watch`，否则 `closed` |

取消/延期由 `RaceEvent.status` 使所有 checkpoint terminal/no-due，不向 tracking 写不存在的状态。历史 tracking
只 adoption 现有六值；非法值 migration fail closed，禁止映射猜测。

### 5.2 Observation 与字段审计

复用 `RaceResultObservation`。它已具备 `observed_at`、`source_updated_at`、HTTP metadata、parser、
raw/normalized SHA、normalized payload、provenance、warning、latency/error、artifact path/size/retention 和
permission classification；只按 schema-delta audit 补齐：

- `data_kind`：time/racecard/result；
- source label；
- registry/contract digest、transport run、Celery task ID；
- identity resolution、completeness 和 finality reason code。

`RaceEventFieldChange` 已有 nullable observation FK、decision、parser/contract/task identity、generation、
operation mode 与 rejection reason，本方案直接复用，不再迁移重复字段。只有实际 schema-delta 审计证明
缺列时才先 nullable 增加，旧记录不破坏性回填，约束收紧放入独立 migration。

### 5.3 来源与结果语义

`RaceResultSourceIdentity` 继续保存 provider identity，但需把当前 provider-name 特判迁移为通用合同资格：

- 增不可变 `region_code`、`identity_namespace`；稳定唯一约束为
  `(source_key, region_code, identity_namespace, external_race_id)`，event 侧 current 唯一约束为
  `(event, source_key, region_code, identity_namespace)`；contract version/digest 不参与稳定唯一键；
- `source_class`：licensed_api/official_operator/trusted_publisher，并绑定数值优先级 300/200/100；
- `finality_capability`：provisional_only/terminal_complete；
- `automation_allowed`、contract/registry/proof digest、valid until；
- 历史 identity 只在现有 `identity_fields` 能确定性给出 region/namespace 时 adoption；无法证明或产生唯一
  冲突的行标为 `review_required`、`automation_allowed=false`，不做名称/日期模糊合并；
- contract 升级只产生新 admission proof，不复制稳定 identity。

`RaceEventRevision` 同时记录：

- `phase`：racecard/provisional_result/confirmed_result/corrected_result；
- `source_label`；
- observation/content/roster digest；
- parent revision 与 correction reason。

来源类别与结果阶段必须正交并仅用于内部审计/仲裁；公开页统一显示“赛果”，不暴露来源类别或内部阶段。

`RaceEventRevisionItem` 与 legacy `RaceEventResult` 各增 nullable
`reported_finish_position`（可重复、正整数）；唯一 `internal_order/finish_position` 继续承担排序和行身份。
所有正式来源以 `reported_finish_position` 保存来源报告名次；legacy `official_finish_position` 可在兼容投影
中镜像同值，但不参与来源类别判断。adoption 仅把已有 `official_finish_position` 复制到 reported；历史
human/reference 只有冻结 source refs/review bundle 能证明时才回填，否则保持 null 并沿用旧页面 fallback，
不从内部唯一顺序猜死热。公开展示优先 reported，再回退 legacy 字段，最后才是内部 order。

### 5.4 Incident 与运行记录

优先复用现有 race-live incident/alert、`TaskExecutionLog` 和 OperationLog。只有现有模型无法唯一表达
`event + provider + data_kind + reason + generation` 去重时，才新增轻量 incident 表；不得以日志文本
搜索承担幂等。

## 6. Enrollment 与未来赛事发现

新增版本化 `RaceDataSyncEnrollment`（每 event 一行）作为 data-sync 选择边界，不复用 lifecycle enforce
membership，也不创建新的 provider registry。字段至少包含 `state=proposed/enrolled/paused/retired`、
standing policy digest、source identity/route digest、event snapshot SHA、projection owner/generation、
enrollment generation、manifest/entry SHA、reason code 与生效/失效时间。

`build_race_data_enrollment_census()` 只读扫描 published 的现有/未来赛事，严格按 canonical duplicate link、
status、manual lock、稳定 source identity、route、owner 与时间质量分类。R0 的 99 场历史快照保留为 census
完整性回归证据；当前发布必须对 standing policy 命中的实时全量 inventory 自动归入 `eligible/enrolled` 或
明确阻断原因，分类总数严格守恒，不能只扫已有 enabled tracking，也不把分类变成逐赛事人工批准。

`apply_race_data_enrollment_manifest()` 只能在全部 runtime/apply/network/public 开关关闭时运行，绑定 exact
commit、standing policy、census cutoff、event/identity/route/owner before snapshot 与 manifest SHA；按 event ID
升序锁定，幂等创建/接管允许的 projection control、tracking、provider checkpoints 和 enrollment 行，并将
owner 由 `unmanaged` CAS 为 `data_sync`。若 owner 已是 `live/historical/manual_paused`，或 source
identity/route 漂移，则单 event 零写并进入
review。disenroll manifest 只停 tracking/checkpoint 并释放本方案 owner，不删除 observation/revision/audit；
baseline 漂移时拒绝。

owner CAS truth table 固定如下：

| before owner | 操作/证明 | after owner | 结果 |
|---|---|---|---|
| `unmanaged` | exact enrollment manifest + expected owner generation | `data_sync`，generation +1 | acquired |
| `data_sync` | 相同 enrollment entry/manifest/generation | 不变 | replay |
| `data_sync` | 已批准 successor manifest + 相同 standing policy + 无 active claim | `data_sync`，manifest 更新且 generation +1 | rotated |
| `data_sync` | exact disenroll manifest + 无 active claim + current baseline 匹配 | `unmanaged`，generation +1 | released |
| `live/historical/manual_paused` | 普通 enrollment/disenroll | 不变 | `writer_owner_conflict` |
| 任意 owner | expected owner/generation/manifest 漂移 | 不变 | `owner_cas_stale` |

历史 `live` 永不由 migration 自动改为 `data_sync`。若未来确需转移，必须使用单独 reviewed transfer
manifest：legacy scheduler/monitor/network/apply 全关、legacy/new queues 均已冻结并完整 drain、无 active
tracking claim、current/LKG/revision baseline 精确绑定，再在单事务执行 `live -> data_sync` 与 generation+1；
失败整场零写。旧代码遇到 `data_sync` owner 时不能写，只能拒绝未知/非 `live` owner。

新发布赛事由每小时 census 发现。只有命中用户授权且未过期的 standing policy（region/provider/data
kind/visibility/status/identity rules 精确绑定）才自动生成并 apply 小批 enrollment；无需逐场批准，策略外
赛事只生成 proposal。纳管事务同时建立 data-sync owner、provider checkpoint 与 lifecycle control；公开
confirmed result 仍必须通过当前 enrollment/generation/contract/manual-lock 等完整 admission。

## 7. Selector 与 claim

`select_due_race_sync_v2_task`：

1. 总开关关闭时在数据库查询前返回 `enabled=false`；
2. 只查询 tracking enabled、`next_poll_at <= now`、允许地区/cohort 的 event；
3. 按 `(next_poll_at, event_id)` 排序并限制 batch；
4. 使用 `select_for_update(skip_locked)` 取得父 claim；
5. 冻结 due provider checkpoint、generation、attempt token、route digest 和 plan hash；
6. commit 后派发专用队列；派发失败时保留可重试状态；
7. 重复 selector 不能产生第二个有效 claim。

worker 完成时验证 attempt token、claim generation、checkpoint lock version 和 event baseline。任何漂移
都只保存可证明安全的 observation，canonical projection 零写。

## 8. 请求合并、single-flight 与限速

对于返回地区/日期整批 racecard 或 results 的 provider：

- cache key 固定为 provider、region、provider local date、endpoint contract、registry digest；
- 单次请求由多个 event 共享，缓存 TTL 初始 150 秒；
- 使用数据库 `RaceLiveHostBudget` 做跨 worker host 间隔和 circuit；
- snapshot 必须包含 payload SHA、fetched_at、完整 pagination evidence 和 races-by-external-ID；
- pagination 缺页、metadata drift、总数溢出或 deadline exceeded 时整份 snapshot 不可用于 projection。

跨进程 single-flight 使用持久 `RaceDataSnapshotLease`（canonical cache key 唯一）：owner token、lease
expiry、attempt generation、state、complete artifact SHA/manifest 和 retry-after。claim 用数据库 CAS；owner
在事务外抓取分页到私有临时目录，完整校验后用原子 rename + 单事务发布 complete manifest。waiter 只以
bounded+jitter 轮询 complete manifest；owner 崩溃或 lease 过期时恰有一个 waiter CAS 接管。pagination
失败/超时只记录 failed/retry-after，partial artifact 永不发布。Redis 只能缓存已完成 manifest，不能成为
lease 或 completeness 真相。

单赛事页面来源仍通过相同 host budget，不能绕过 registry transport。

## 9. 时间与 reschedule 协调器

扩展 Slice A，新增唯一 provider-neutral `apply_race_schedule_observation()`。所有会同时接触 lifecycle、
event 或 projection 的写路径必须服从同一全局锁图：

```text
active lifecycle registry shared advisory barrier（涉及 lifecycle 时）
-> RaceEventLifecycleEnforceMembership（若需要，event_id 顺序）
-> RaceEventLifecycleControl
-> RaceEvent
-> RaceEventProjectionControl
-> RaceEventLiveTracking
-> provider checkpoints
-> source identity
-> observation
-> revision / result / participant / runner rows
-> field authority rows
```

不存在的 optional row 也必须按该顺序查询/创建，不能先锁后序对象再回头锁前序对象。现有
`apply_race_lifecycle_decision()` 与 `apply_registry_lifecycle_decision()` 的 control -> event 主序保留；
现有 Slice A `_reconcile_racecard_observation_atomic()` 当前 observation -> event 的逆序也必须重构：入口可先
无锁读取 observation 的 event ID/SHA 作为 hint，但进入 transaction 后必须按 event -> projection -> tracking
-> source identity -> observation -> participant/runner -> authority 顺序重锁并重验 hint，不能持有 observation
锁再回头锁 event；
现有 `complete_race_event_live_checkpoint()`、`checkpoint_or_promote_race_event_live_pre_off()`、
`apply_race_live_racecard_refresh()`、`apply_race_result_observation_revision()`、
`restore_race_live_provisional_policies()`、`restore_last_provisional_result()` 以及 enrollment/rollback 中
event/control/tracking 逆序路径，必须先迁移到共享 lock coordinator 或按此图重构，之后才可接入新 writer。
不能只让新函数遵守而保留交叉死锁路径。

事务内执行：

- 校验 aware time、IANA zone、local/UTC round trip；
- 运行同值/同源更新/跨源冲突/manual lock 决策；
- 写 field change；
- applied 时更新 event；
- bump lifecycle schedule/claim generation 与 live claim generation/lock version；
- 清 active token/lease，重算 lifecycle `next_refresh_at` 与 provider checkpoints；
- 写 operation audit。

PostgreSQL concurrency gate 必须真实并发 schedule×lifecycle、schedule×result projection、
schedule×live checkpoint、racecard×schedule、racecard×result，并注入 mid-transaction abort/retry；要求 bounded completion、无 deadlock、
无 lock-order inversion，且 observation/field/event/generation/result/status 不发生部分提交。

transaction rollback 不失效缓存；commit 后每个 event 恰好失效一次。

## 10. Racecard reconciliation

1. parser 输出严格 roster schema 和每个 participant 的 provider identity；
2. 先按 provider participant ID 命中 `RaceEventParticipantSourceIdentity`；
3. 没有 ID 时只允许 event-scoped stable key，不做跨 event 自动合并；
4. 逐字段比较 horse number、barrier、jockey、trainer、weight、status；
5. 明确退赛/补出生成新 racecard revision；缺行保持 unknown，不删除；
6. 内容 hash 相同重放 noop；并发 revision 由 projection control 分配唯一编号；
7. current pointer 只在完整、无冲突 revision 上移动；LKG pointer 永远保留。

legacy `RaceEventRunner` 作为公开兼容投影；participant/revision 是权威审计层。若 legacy runner 与新
projection 已有冲突，先生成 review incident，不强制覆盖。

## 11. Result finality 与 projection

### 11.1 Parser 输出

normalized result 至少包含：

- provider/external race identity；
- source status 与映射后的 finality；
- declared/started/result runner 集合；
- internal order、authority-neutral reported finish position、仅官方来源可写的 official finish position、
  non-finish/withdrawn/cancelled 状态；
- source updated/fetched time 和内容 SHA。

### 11.2 完整性判断

`result_completeness_decision()` 是纯函数：

- terminal + 全 runner 守恒 + 唯一身份 + 合法顺序 -> confirmed candidate；
- 明确 provisional -> provisional candidate；
- partial、unknown、DORMANT、重复身份、仅头马、仅部分 Also Ran -> observation only；
- 与 current confirmed 不同且有 correction marker -> correction candidate；
- 与 current confirmed 不同但无 correction marker -> conflict incident。

### 11.3 Immutable revision 与原子公开

`apply_data_sync_result_observation()` 是唯一结果投影入口。它在一个 transaction 内按以下顺序执行：

1. 锁定并重验 exact provider claim：event、projection owner/generation、enrollment/generation/entry SHA、
   active attempt token、claim expiry、plan SHA 与 checkpoint lock version；
2. 锁定 observation/source，重验身份、合同、完整性、manual lock 与 source-class 仲裁；
3. 以 event/kind/content SHA 幂等创建 immutable `RaceEventRevision` 和 items/evidence；
4. `result apply/public` 关闭或候选未赢得仲裁时，revision 保持未发布且不移动 current；
5. 开关开启且候选胜出时，在同一事务替换 legacy `RaceEventResult`、移动 current/LKG pointer、写
   `result_confirmed_at`、tracking 状态和唯一 lifecycle transition，并推进 event 为 `finished`；
6. commit 后失效公开缓存；checkpoint/父 due 由随后仍需通过同一 exact claim CAS 的 completion 更新。

网络请求发生在事务外，因此步骤 1 必须在每一次 schedule/racecard/result canonical apply 内重新执行。
claim 在网络期间过期、被新 worker 接管，或 enrollment/owner/plan/checkpoint 漂移时，只允许保留已经形成的
immutable observation；canonical、revision、runner/result、status 和 checkpoint 全部零写。claim completion
和 failure release 也显式拒绝 `claim_expired`，不能由迟到 worker 清理或重排新任务。

分支固定如下：

| runtime/仲裁 | revision/result 行为 | status 行为 |
|---|---|---|
| apply/public 关闭 | 可保留合格 immutable revision，legacy/current 零写 | 零写 |
| stale/expired claim、identity/contract/manual lock 失败 | canonical 与 revision 零写，返回 reason code | 零写 |
| 高优先级或同源更新胜出 | 同事务写 revision、legacy projection 与 current/LKG | 同事务写唯一 `finished` transition |
| 低优先级候选 | 保留未发布 revision，不覆盖 current | 零写 |
| 已存在相同 content SHA | replay 既有 revision，不重复投影 | 不重复 transition |
| correction 胜出且 correction flag 开启 | 新 revision 精确 supersedes current，历史保留 | 保持 `finished` |

单 event 事务失败不影响其他 event；同 event 内不允许结果行、current pointer 和状态部分提交。正常赛事只需
全局/分项开关与 standing-policy 自动 enrollment，不需要逐场人工确认。

## 12. 人工审核任务的定位

现有 `scheduled-race-result-review` 保留为异常兜底：

- 不具备 `race_datetime` 的历史/残缺赛事补偿；
- 自动 route 缺失、身份冲突、部分赛果或 T+24h stale 的人工 fallback；
- 自动链长期阻断时的离线对照来源。

该旧链自身仍要求 bundle/event digest 的人工批准，但不会阻断或批准新的正常自动链。自动链不能伪造
approval，也不能复用 `human_reviewed_reference` authority。

## 13. 开关与配置

保留主干 `RACE_DATA_SYNC_*` 命名空间并扩展，全部默认关闭；`race_sync_v2` 不得出现在业务开关名中：

```text
RACE_DATA_SYNC_ENABLED=false                  # 已存在，唯一总 admission
RACE_DATA_SYNC_ENABLED_PROVIDERS=             # 已存在
RACE_DATA_SYNC_ENABLED_REGIONS=               # 已存在
RACE_DATA_SYNC_ENABLED_FIELDS=                # 已存在
RACE_DATA_SYNC_SCHEDULER_ENABLED=false        # 新增
RACE_DATA_SYNC_ALLOW_NETWORK=false            # 新增
RACE_DATA_SYNC_ENABLED_DATA_KINDS=            # 新增
RACE_DATA_SYNC_SCHEDULE_APPLY_ENABLED=false   # 新增
RACE_DATA_SYNC_RACECARD_APPLY_ENABLED=false   # 新增；仍由 Slice A writer 执行
RACE_DATA_SYNC_RESULT_APPLY_ENABLED=false     # 新增
RACE_DATA_SYNC_RESULT_PUBLIC_ENABLED=false    # 新增
RACE_DATA_SYNC_CORRECTION_APPLY_ENABLED=false # 新增
```

开关必须逐层相交，任一关闭都不能被更宽开关覆盖。provider、region、data kind、cohort 与 public
admission 独立关闭。lifecycle enforce 仍使用现有独立 trust root，不能被 sync 总开关隐式提升。
迁移期 `RACE_LIVE_*` 保持 legacy-only：任何配置组合若令 legacy 与 Slice A 同时拥有同一 event/data-kind
写权限，统一拒绝为 `writer_owner_conflict`，不规定“谁先到谁写”。

## 14. Celery 与发布控制面

Compose 新增 `race_sync_v2_worker`：

- `-Q race_sync_v2`，不得消费 `race_live` 或普通 `celery`；
- 独立 concurrency/prefetch/soft-hard limit/max-tasks-per-child/memory；
- 仅挂载受限 artifact、registry 和 secret 文件；
- 网络 admission 与普通新闻 worker 分离；
- health 以 worker ping、queue lag、DB claim 和固定离线 fixture smoke 组合判断。

Beat 只发送 selector；selector 设置 55 秒 expiry。provider task 携带 event ID、generation、attempt
token 和 plan hash，不携带 URL、credential 或任意 shell 参数。

部署前不得对遗留 `race_live` 队列做 destructive cleanup。新队列必须从 0 开始，并在关闭态证明
selector/network/business writes 都为 0。

新增 service 不能只改 Compose。R0 同一发布单元必须修改并测试：

- `deploy/run_application_release.sh`：冻结 `race_sync_v2_worker` 当前 running/node 与恢复意图；probe 失败
  在任何 stop 前 fail closed；将运行中的 node 加入完整 Celery drain；按 beat -> drain -> ordinary worker ->
  race_live/race_sync_v2 workers -> web 停止，成功后只按冻结意图恢复；
- `deploy/manual_release.sh`：将新 worker 纳入“全部应用服务已明确停止”检查，running/restarting/unreadable
  任一状态都拒绝 one-shot；
- `deploy/resume_stopped_release.sh`：将新 worker 纳入前置 stopped 检查，并读取独立、mode-600、
  compose/action/HEAD 绑定的 frozen intent；intent 不可信时只跳过该 worker 的恢复并告警；
- `deploy/rollback.sh`、`deploy/rollback_lowcost.sh`、`deploy/rollback_pre_single_owner.sh`、
  `deploy/resume_rollback_control_state.sh` 与被复制到 immutable control dir 的 release helper：catalog/SHA、
  drain、stop、restore、completed receipt 都必须包含新 worker；
- `deploy/race_live_state.sh` 要么推广为逐 service intent helper，要么新增同等严格的 sync-worker helper，
  两个 worker 的 intent 文件不能相互覆盖；
- 两个生产 Compose 文件都定义新 worker并固定同一候选 image revision；回滚到不含该 service 的旧镜像时，
  control plane 必须按 target Compose service catalog 显式判定“不存在且不恢复”，不能把 unknown 当 stopped。

shell/Compose integration RED 覆盖 worker 原为 running/stopped、`compose ps` 或 inspect 失败、drain node
缺失、release 中断后 resume、rollback 中断后 immutable-control resume、旧 target 无 service 六类路径；每条
都校验服务最终状态与 frozen intent 一致。

## 15. Artifact、容量与保留

- raw response 写入专用 generation 目录，拒绝 symlink/path traversal，文件先 fsync 后原子 rename；
- canonical manifest 列出 source identity、request metadata、raw/normalized SHA、parser/contract digest；
- raw 不含 credential/cookie/header；压缩前后 size 均有上限；
- ordinary raw 在线保留 90 天，hash/normalized/revision/ledger 长期保留；
- conflict、人工确认、confirmed/corrected result 的证据设置 audit hold，不自动清理；
- cleanup 只删除已过期大字段/文件，不能删除 DB ledger 或破坏 FK。

容量 admission 在发请求前执行，配置包含：单 payload 压缩前/后上限、provider+region 每日 bytes/request
预算、artifact root 总量 high/low water、最小 free-disk bytes、每次 cleanup 最大 rows/bytes 与 cadence。
配置键固定为 `RACE_DATA_RAW_MAX_COMPRESSED_BYTES`、`RACE_DATA_RAW_MAX_UNCOMPRESSED_BYTES`、
`RACE_DATA_RAW_DAILY_PROVIDER_REGION_BYTES`、`RACE_DATA_RAW_DAILY_PROVIDER_REGION_REQUESTS`、
`RACE_DATA_RAW_ROOT_HIGH_WATER_BYTES`、`RACE_DATA_RAW_ROOT_LOW_WATER_BYTES`、
`RACE_DATA_RAW_MIN_FREE_DISK_BYTES`、`RACE_DATA_RAW_CLEANUP_MAX_ROWS`、
`RACE_DATA_RAW_CLEANUP_MAX_BYTES`、`RACE_DATA_RAW_HOLD_ALERT_BYTES`；缺失/非法值时 network admission 关闭。
生产值不能凭方案硬编码；G2 必须根据 live disk、现有约 45GB backup、增长率与保留期给出 sizing proof 后
冻结配置。预算或磁盘不足时在 transport 前返回 `artifact_capacity_blocked`，network=0、business write=0。
audit hold bytes 单独计量且不可被 cleanup 删除；hold 超预算、cleanup 失败或无法回到 low water 时自动关闭
该 provider 网络并告警，不能继续抓取等待磁盘耗尽。

## 16. 监控面板

推荐按 `region/provider/data_kind` 展示：

- upcoming event、identity route、datetime、racecard、result coverage；
- next due、queue lag、active claim、stale lease、checkpoint circuit；
- request status/latency/budget/schema drift；
- observation/revision/field decision；
- independent upstream-terminal-available、terminal detection、confirmed publication、blocked alert coverage
  和 terminal-to-public histogram；
- public verifier mismatch、correction、conflict/manual-lock incident。

报警分级：

- P0：跨 event 写入、错误赛果公开、manual lock 被覆盖、重复 current revision；
- P1：T+30 无结果且无告警、terminal 后 10 分钟未公开、queue 无消费者；
- P2：单 provider circuit、route 即将过期、时间/出马表覆盖下降。

## 17. 代码切片与发布单元

实现内部仍按五个切片组织，但按用户授权合并在同一 PR #108 和同一隔离 release；切片边界用于测试、
开关启用与止损，不再要求五个独立 PR 或五次人工批准：

1. R0：扩展现有 Slice A roster/flags，加入 enrollment census/manifest、provider checkpoint、single-flight、
   selector、`race_sync_v2` queue/worker 与完整 release control-plane，全部关闭；
2. R1：race time observation、字段 reconciliation 和原子 reschedule，先只观察；
3. R2：racecard revision、runner merge 和公开投影；
4. R3：result observation、finality/completeness、confirmed/corrected revision，public 关闭；
5. R4：唯一 lifecycle/public transactional API、独立 reference SLO/告警、地区灰度和 correction watch。

R1/R2/R3 都不得绕过 R0 的 registry/checkpoint/queue。R3 在 R4 前不自动公开，不直接改变赛事状态。
