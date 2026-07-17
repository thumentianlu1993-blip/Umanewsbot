# 准实时赛事赛果设计

## 设计摘要

复用现有 `RaceSeries`、`RaceEvent`、`RaceEventRunner`、`RaceEventResult`、`RaceEventDataCandidate`、公开赛事页、术语展示和 Redis cache 基础，但新增准实时专用的“来源观测 -> canonical revision -> 当前投影”链路。历史 importer、历史 crawl orchestration 和 historical runner 只作为解析、证据、锁和 verifier 模式参考，不直接承载准实时任务。

调度选择 Celery Beat 的轻量 due-selector 加独立 `race_live` queue/worker。理由是目标数小、任务短、需要定时重试且项目已有 Celery/Redis；独立 worker 可避免新闻 worker 被网络慢请求占满。Beat 只选 due target 并发消息，host 限速和网络访问发生在独立 worker。长期、重型、artifact 驱动的历史 runner 在进程、队列、runtime、lease 和 checkpoint 上保持独立，但其数据库投影写入口必须接入共享 ownership arbitration。

## 当前代码复用审计

| 现有能力 | 当前实现 | 复用结论 | 必要变化 |
| --- | --- | --- | --- |
| 赛事身份 | `RaceSeries`、`RaceEvent(year, slug, race_series)` | 直接复用 | 新增外部 source race identity 和 identity review 记录 |
| 重点赛事 | `MajorRaceEvent`、`RaceEvent.priority/is_featured` | 复用选择条件 | 明确 2025+ 等级/白名单与 tracking allowlist |
| 出马表 | `RaceEventRunner` | 复用当前投影和前台 | 新增稳定 participant identity、不可变 racecard revision 和共享投影仲裁 |
| 赛果 | `RaceEventResult` | 复用当前投影和前台 | 不再直接覆盖式导入；由 canonical revision 原子投影 |
| 暂定/正式 | `is_confirmed`、`result_confirmed_at` | 字段可迁移兼容，但语义不足 | 新增事件级 live state、revision status、官方来源与确认时间 |
| 改判/同着 | `official_finish_position` 可重复；内部 `finish_position` 唯一 | 同着显示可复用 | revision item 保存 source/order/official positions，投影继续用内部稳定顺序 |
| 候选池 | `RaceEventDataCandidate` | 非 live-owned 赛事继续沿用 | live-owned 赛事的人工候选转为 observation/revision，禁止绕过仲裁直接覆盖 |
| 数据应用 | `apply_data_candidate()` 在事务内，但 runners/results 全删重建 | 接入点可复用，覆盖写法不可复用 | 历史 importer、candidate apply、后台人工和准实时 apply 全部经过同一投影仲裁服务 |
| 动态字段 | `update_runner_dynamic_fields()` | 可复用匹配思想 | 加锁、来源优先级、字段 provenance 和幂等哈希 |
| 抓取编排 | `race_event_crawl_orchestration.py`、source cache、manifest | 复用 adapter contract、证据和字段 sanitization 思路 | 准实时不能生成重型 runtime plan；改为轻量 observation contract |
| 地区 adapter | JRA/NAR/HKJC/Sporting Life/ZEturf/HRN/Equibase 历史工具 | 只复用 parser fixture 与 normalization 片段 | 不把历史页面抓取器自动升级为实时生产来源；每源重新做延迟/条款 proof |
| 调度 | `CELERY_BEAT_SCHEDULE` 和现有 task logging | 复用 Beat/任务框架 | 新建独立 queue、worker、route、limits、selector 和 kill switches |
| 历史 runner | DB lease + 文件锁 + checkpoint 的独立 Docker runner | 只复用安全原则 | 准实时绝不复用其表、runtime、容器、网络/写角色 |
| 历史 detail receipt/chunk | `HistoricalRaceDetailImportReceipt`、原子 chunk apply/reconcile/verifier | 复用不可变身份和原子终态 | handoff 纳入 receipt/bundle/chunk/current-year due；完成 payload/verifier 增加 projection owner generation 与 revision 身份 |
| 当前年 due | `current_year_due` layer、2026 descriptor 与 new formal policy | 复用正式目标身份与 due/not-due 分层 | 2025+ event 与 live ownership 必须逐 ID 移交，不能让历史 current-year apply 与 live task 并写 |
| 前台 | `public_race_calendar/detail`、race templates、term display | 直接复用 | 增加暂定/正式/改判 badge、更新时间、stale/conflict 状态 |
| 缓存 | 赛事 sitemap/year cache | 复用 invalidation helper | 新增事件级短 TTL cache/version key，revision apply 后精确失效 |

## 领域模型

### 1. `RaceEventLiveTracking`

一场赛事一行的调度/checkpoint 投影：

- `event` unique FK
- `state`：六态状态机
- `tracking_enabled`：是否进入准实时选择器；发布模式不存入本表
- `next_poll_at`、`window_started_at`、`window_ends_at`
- `last_attempt_at`、`last_success_at`、`last_observation_hash`
- `provisional_published_at`、`official_published_at`、`corrected_at`
- `consecutive_failures`、`circuit_reason`、`stale_at`
- `lock_version`、`claim_generation`、`active_attempt_token`、`claim_expires_at`、`checkpoint_payload`
- `source_route_version`、`selection_reason`

索引：`(tracking_enabled, next_poll_at)`、`(state, next_poll_at)`、`(event, state)`。延期/取消继续落在 `RaceEvent.status`，tracking 保存停止理由。

### 2. `RaceEventProjectionControl`

每场赛事一行，是所有 runner/racecard/result 物化投影的唯一写入仲裁点：

- `event` unique FK。
- `write_owner`：`unmanaged | historical | live | manual_paused`。
- `owner_generation`、`owner_manifest_sha256`、`owner_changed_at/by`。
- `current_racecard_revision`、`last_known_good_racecard_revision`。
- `current_result_revision`、`last_known_good_result_revision`。
- `next_racecard_revision_no`、`next_result_revision_no`。

历史 chunk importer、`apply_historical_target_candidate()`、`apply_data_candidate()`、后台 inline/人工操作和 live apply 必须锁定本行并调用同一 arbitration service。`live` 所有权下，旧历史/候选入口直接 apply 必须 fail closed；人工改动先形成 observation/revision。后续确需历史修复时，先暂停 live、以 manifest 精确移交所有权，修复完成后再显式交还。非 live-owned 赛事保持既有历史行为，但也通过该服务记录 owner generation，避免未来接管时出现无痕覆盖。

历史 receipt 兼容规则：同一个 chunk 的业务投影、candidate APPLIED、canonical revisions、owner generation snapshot 与 receipt COMPLETED 必须仍在一个外层事务完成；completion payload 固定 event/revision/content hashes，verifier 同时核对 candidate provenance、current projection pointer 和 materialized counts。STARTED/ABANDONED reconcile 不得越过 live owner；live ownership 存在时 fail closed，并要求先走精确 handoff/owner transfer。

### 3. `RaceResultSourceIdentity`

稳定绑定赛事与各来源：

- `event`、`source_key`、`external_race_id`
- `canonical_url`、`host`
- `identity_fields`（date/course/race_no/distance/grade）
- `review_status`、`reviewed_by/at`
- unique `(source_key, external_race_id)` 和 `(event, source_key)`

自动轮询前必须 approved；漂移进入 review，不自动换绑。

来源注册表还必须保存 `terms_status`、`automation_allowed`、`proof_network_allowed`、证据 URL/SHA、`valid_until` 和 `registry_digest`。任何真实联网模式都先核验：生产/正式 shadow 要求 `approved + automation_allowed`；一次性 proof 要求显式 `proof_network_allowed`、未过期证据、批准 manifest 和请求预算。unknown、expired、digest drift、manual、blocked 一律 fail closed；offline fixture 不受此门禁影响。

### 4. `RaceEventParticipant` / `RaceEventParticipantSourceIdentity`

稳定参赛者身份独立于会变化的马号、档位和骑师：

- participant：`event`、`stable_key`、可选 `horse_profile/term`、规范名、国家/地区、出生年、`review_status`；unique `(event, stable_key)`。
- source identity：participant、source identity、`external_runner_id`；非空 external ID 在同一 source race 内唯一。
- 自动匹配顺序：source runner ID -> 已审核 HorseProfile/Term -> 唯一的规范名+国家/地区+出生年；马号/档位仅作一致性检查，不能单独作为 identity。
- 同名、缺字段或 ID 漂移不能猜测绑定，进入 identity review；骑师更换、马号变化、退赛再恢复只形成 racecard revision，不改变 participant。

### 5. `RaceResultObservation`

append-only 来源证据：

- source identity、`observed_at`、`source_updated_at`、`http_status`
- `etag/last_modified`、`parser_version`
- `raw_sha256`、`normalized_sha256`
- `result_phase`（racecard/provisional/official/corrected/unknown）
- bounded `normalized_payload`、字段 provenance、解析 warning
- latency、error_code、retryability
- unique `(source_identity, normalized_sha256, result_phase)`

原始响应只进入受控 private artifact/cache，记录路径、大小、SHA、保留期和许可分类；数据库不保存整页 HTML、评论或大段版权内容。

### 6. `RaceEventRevision` / `RaceEventRevisionItem`

racecard 和 result 共用 canonical、不可变业务修订：

- `event`、`kind=racecard|result`、按 kind 递增的 `revision_no`、`phase`
- `content_sha256`、`source_authority`、`decision_reason`
- `primary_observation`；supporting evidence 放在 append-only link 表，不能修改 revision 本体
- `supersedes`、`published_at`、`official_confirmed_at`
- `conflict_status`、`applied_by`（自动 service 或人工）
- item 保存 participant、source order、内部 order、官方名次、状态、时间、差距、马号/档位/骑师快照和字段 provenance

约束和并发规则：

- unique `(event, kind, revision_no)` 和 `(event, kind, phase, content_sha256)`。
- item unique `(revision, participant)`、unique `(revision, internal_order)`；`official_finish_position` 可重复以表达同着。
- `supersedes`、current pointer 和 last-known-good pointer 必须同 event/kind；用 PostgreSQL deferred constraint trigger 防止跨赛事、跨 kind 或指向未来/自身。
- 新 revision number 在锁定 `RaceEventProjectionControl` 后从对应 counter 分配；死锁/serialization failure 仅做有界重试。
- apply CAS 同时校验 attempt token/claim generation、owner generation 和旧 current pointer；过期网络响应只能保存为 observation，不能推进 revision 或投影。
- revision、items、evidence link、current/last-known-good pointer、`RaceEventRunner/Result` 投影、badge 字段和 OperationLog 在一个短事务内原子提交。

racecard item 的完整状态至少包括 `declared | running | scratched | withdrawn | reinstated | non_runner | unknown`；result item 至少包括 `finished | dead_heat | disqualified | did_not_finish | pulled_up | unseated_rider | fell | refused | non_runner | unknown`。既有枚举通过 migration 扩展；无法映射时保留 raw 值并写 `unknown`，不得丢弃参赛者。

当前 `RaceEventRunner/Result` 是 current revision 的物化投影。provisional 与 official 内容相同仍生成状态 revision，但不需要删除重插相同 result rows。`RaceEvent.result_confirmed_at` 仅在 official/corrected 时设置。回滚只把 current pointer 原子切换至已验证的 last-known-good revision 并重建投影，绝不删除审计链。

### 7. `RaceLiveHostBudget`

每 host 共享的 DB/Redis 限速状态：

- `host`、`min_interval_ms`、`next_allowed_at`
- `consecutive_failures`、`circuit_open_until`
- `last_status`、`updated_at`

用 Redis 原子 token/lock 做快速限速，DB 保存可恢复 checkpoint。Redis 不可用时 fail closed 或使用更保守 DB 锁，不能无限制直连来源。

## 状态转移和来源决策

| 当前状态 | 输入 | 下一状态 | 自动条件 |
| --- | --- | --- | --- |
| scheduled | approved racecard identity + 完整 runners | racecard_ready | 主来源或两个独立补充来源一致 |
| racecard_ready | 到达 off time/来源标为 off | awaiting_result | 时间门或官方状态 |
| awaiting_result | 完整非官方/聚合 API 赛果 | provisional_result | 身份一致、字段门禁通过、无官方冲突 |
| awaiting_result | 完整官方赛果 | official_result | 官方来源且结果已正式/称重完成 |
| provisional_result | 官方同结果 | official_result | canonical hash 等价或差异可解释 |
| provisional_result | 官方不同结果 | official_result | 新 revision，保留 provisional，原子替换投影 |
| official_result | 官方后续不同结果 | corrected_result | 官方 revision/公报/管理员批准证据 |
| corrected_result | 再次官方修订 | corrected_result | revision_no 递增 |

经批准且完成 proof 的商业 API（当前为 The Racing API）可以单独形成并公开 provisional，但不能 official；不要求先等第二来源或官方来源返回。其他 B/C 来源一致只能提高 provisional 置信度；官方 A 级来源异步决定 official/corrected。来源删除结果、返回空数组或字段减少时不生成空 canonical revision。

## 地区路由与 proof 结论

| 地区 | 自动主路由候选 | 官方复核 | 查漏/人工来源 | 当前生产资格 |
| --- | --- | --- | --- | --- |
| 英国 | The Racing API Free/Basic | BHA 的官方赛果/更正、赛场官方 | Racing Post、Sporting Life | TRA 仅在 proof permission 与 handoff 通过后可联网；RP/SL 未授权自动化，BHA 接口/许可待验证 |
| 法国 | The Racing API | France Galop | PMU、Geny、Racing Post | TRA 仅在 proof permission 与 handoff 通过后可联网；France Galop/PMU/Geny 自动化条款待确认 |
| 香港 | The Racing API | HKJC results、weighed-in、Stewards | HKJC 人工核验 | TRA 完整结果可先形成 provisional；HKJC 异步确认 official/corrected |
| 日本中央 | The Racing API | JRA | netkeiba | TRA 完整结果可先形成 provisional；JRA 异步确认 official/corrected，官方访问/再发布许可仍需审计 |
| 日本地方 | The Racing API | NAR | 既有第三方只查漏 | TRA 完整结果可先形成 provisional；NAR 异步确认 official/corrected，条款许可仍是硬门禁 |
| 美国 | 赛马场官方 feed/页面（逐场审批） | Equibase/监管/赛场 official chart | HRN、The Racing API Core | 没有统一已批准自动主源；HRN robots/许可阻断，TRA Core 覆盖不足，NA add-on 不采购 |

Sporting Life、Racing Post、Geny、HRN 等只可用于人工定位、fixture 构造或获得许可后的 adapter；不得把现有历史 parser 的成功当作实时稳定性或授权证据。

## 来源 proof artifact

每次 proof 写入 `runtime/realtime_race_result_proofs/<run_id>/`（默认 ignored、无生产写入）：

- `manifest.json`：run、代码 SHA、来源、host、赛事 allowlist、时间窗、条款快照 SHA。
- `requests.jsonl`：脱敏 URL、时间、状态、耗时、bytes、ETag、retry-after。
- `observations.jsonl`：规范化事实和哈希，不含评论/评级。
- `latency.csv`：scheduled off、来源首次 racecard/provisional/official、本站观测时间。
- `field_matrix.csv`：字段存在率和语义。
- `coverage.csv`：目标/命中/错配/缺失。
- `failures.csv`：403/429/5xx/parse/identity/terms。
- `summary.json`：p50/p95、覆盖率、字段完整度、结论。

proof 工具默认 fixture/offline；真实网络必须显式 `--allow-network --manifest <approved>`，只读来源、禁止 DB commit，带全局请求预算、host 间隔、最大 bytes、timeout、cache SHA 和 resume。

真实网络还要求历史任务完成安全交接，并在 manifest 中固定 source registry digest 与 `proof_network_allowed` 证据。未交接、证据过期或 registry 漂移时命令在发出首个请求前失败。

## The Racing API Free 实测与 Basic 门槛

### Free 实测

1. 用户自行创建 Free 账户并把 Basic Auth 凭据放入本地 secret；工具只报告 credential present，不回显。
2. 先调用 regions/courses 建立 code mapping，再对当天/明天 racecards 和当天 results 做批量请求。
3. 连续覆盖至少四个真实赛日、每地区至少 10 场候选，其中至少 3 场属于该地区正式等级目标；不足则延长观察日历，不用普通赛事冒充重点覆盖。香港按 G1-G3，日本按 G1-G3/JpnⅠ-Ⅲ 分层统计；J-G1-3 单列能力 proof，不得用平地样本代替。
4. 记录 API race ID 稳定性、出马表字段、退赛变化、结果状态、全部参赛者、未完赛/DQ/同着、source update 和本地 observed 时间。
5. 与地区官方来源人工对照，计算 target coverage、identity precision、runner completeness、result completeness、p50/p95 延迟和 revision 一致率。

### 日本 J-G1-3 独立 proof 与 deferred contract

- 原始目标池始终包含正式总账内全部 J-G1/J-G2/J-G3；普通日本 proof 或 selector 不得预先排除。
- 观察窗为历史 handoff 后首个可观测日起连续 90 天，窗口内全部合资格赛事均入分母；最低通过样本为 3 场已完赛赛事，并覆盖窗口内实际举办的每个 J-G 等级。
- 第 30 天记录来源审计 checkpoint，但 proof 至少持续 90 天。90 天时仍无获准自动化来源，或已达到最低样本但 identity/字段/status/延迟任一正式门槛失败，可形成延期理由；样本不足则继续收集至最长 180 天，仍不足记录 `availability_gap`。
- deferred artifact 是带 SHA 的不可变 manifest，包含 `original_target_count`、`active_target_count`、`deferred_target_count`、event IDs/grades、逐项原因和证据、`approved_by/at`、`review_due_at`。只有用户显式批准且未过期时 selector 才按其精确清单排除。
- `review_due_at` 不晚于批准后 180 天，并安排在下一场合资格赛事前；过期立即恢复为 active target。任何报告同时展示 original/active/deferred，deferred 非零时禁止使用“日本完整范围通过”。

### Basic 升级客观门槛

同时满足才向用户建议购买一个月 Basic：

- 正式目标命中率 100%，赛事身份 precision 100%。
- 完整赛果率至少 99%，且 G1-G3 样本无漏马/错名次/把暂定当正式。
- 上游首次可用后的暂定 p95 不超过 10 分钟。
- Free 的基础字段明确缺少至少一个已审核的必需字段，而官方文档/支持书面确认 Basic 会提供。
- 预计 Basic 能替代至少一个不稳定页面 adapter，或每月节省至少 4 小时人工核对。
- 复核最新价格、税、退款、数据使用和再发布条款后，用户单独批准购买。

若 Free 在覆盖或延迟失败，升级 Basic 不能被当作默认修复；先向支持确认计划层级是否影响覆盖。美国 Core 目标覆盖失败也不能自动购买 North America add-on。

## 发布模式与覆盖优先级

发布模式是独立唯一枚举 `off | shadow | provisional_public | official_public`，不与 tracking state 混用，并按该顺序形成权限等级。配置合并是单调收紧而不是层级覆盖：

1. global 是必填上限，缺失/未知即 `off`。
2. 适用的 region、source、event 配置分别是额外上限；缺失继承当前上限，显式未知/冲突/过期视为 `off`。
3. `effective_mode = min(global_cap, region_cap, source_cap, event_cap, terms_cap)`；任一 cap 为 `off`，结果必为 `off`。
4. event allowlist 只决定目标是否可进入相应 phase，不能提升 cap；来源条款/kill switch 也只能降低权限。

因此 global off + event public、region off + event public、source off + event public 均为 off。`shadow` 可持久化 observation/revision，但不更新公开 current pointer/投影；公开模式仍受状态机和来源级别限制。

`provisional_public` 的同步发布条件不包含“官方 observation 已存在”。条件是：The Racing API source identity 已批准、赛事与全部参赛马身份无歧义、完整赛果 schema/状态通过、没有人工锁或高等级冲突、赛事已进入精确 allowlist，且官方二次复核路由已经配置。官方复核在发布后并行执行；未在 T+2h 到达时告警，但不撤下正确标注的暂定赛果。

### 唯一 publication admission 与公开读取门

新增持久化控制面：

- `RaceLivePublicationPolicy`：`scope_type(global/region/source/event)`、`scope_key`、`mode`、`version`、`registry_digest`、`coverage_proof_digest`、`valid_until`，作用域唯一。
- `RaceLiveEventPublicationAllowlist`：event、最大 mode、source key、官方复核 route/version、coverage proof digest、enabled、version。
- `RaceLiveOfficialMarkerContract`：地区/source、允许的 official/corrected marker 类型、parser version、contract digest、有效期和审核状态。
- `RaceLiveOfficialVerificationIncident`：event、provisional revision、route/version、以最新 off time 锚定的 deadline、状态、last/next probe、opened/resolved 时间；幂等键为 event + provisional revision + route version。

唯一入口 `admit_race_live_publication()` 在 projection control 锁事务内：

1. 重读 observation、source identity、current pointer、global/region/source/event policy、allowlist、terms/registry 和 coverage proof。
2. 以版本/digest 重新计算 effective mode；任一缺失、过期、off、digest drift、非 allowlist 或 proof 不覆盖本 event 都拒绝。
3. 从当前获准 racecard revision/expected-participant manifest 取完整参赛全集；逐项读取 participant review 状态和 runner/result 人工锁，按 scratched/withdrawn/non-runner 的显式规则比较 incoming result，拒绝缺马、额外马、pending/conflict identity 或并发人工锁。
4. 对 `the_racing_api` 强制 source authority 为 supplemental；首次完整 TRA observation 只可产生 provisional。
5. admission 通过后在同一事务创建/晋级 revision、投影和 publication audit；adapter、fixture runner、shadow promotion 都不能再传 `project_current` 或最终授权布尔值。

policy/allowlist/registry/coverage proof 的版本和 digest 进入 publication audit。任何配置在 admission 检查后发生变化都会使 CAS 失败并重试，而不是使用旧检查结果公开。

公开页面使用独立 `resolve_race_live_public_read()`，每次按 event/current revision/source 和 policy version 计算；cache key 包含 publication policy version。切换任一适用 scope 为 off 时，在事务提交后失效详情、结果列表和 sitemap cache，使已发布准实时 revision 立即隐藏；重新开启只显示当前仍获准的 revision，不删除审计。

### 官方 marker 与异步复核 incident

官方 adapter 先写不可变 observation 和 marker evidence，evidence 固定 marker contract digest、marker type、原始响应 SHA、parser version 和 source timestamp。apply 不接受裸 `official_marker=True`：

- 当前为 provisional 时，首个合格官方结果无论内容相同或不同均生成/晋级 `official_result`；不同内容 supersede TRA revision 并保留双方证据。
- 当前已为 official 时，后续不同官方内容才生成 `corrected_result`。
- corrected 自动公开要求 marker contract 允许，且 source/event correction gate 均显式开启；默认只进入 review/后台证据。
- 官方结果尚未返回不阻止 TRA provisional 首发，但官方 route 在 admission 时必须已配置、版本有效且可执行；否则该 event 不能进入 provisional 灰度 allowlist。已发布后 route 才失效时保持 provisional、开一次 incident 并告警。
- deadline 锚定最新有效 off time +2h；延期会更新 off time、deadline 和 route audit。官方一致关闭 incident，官方冲突升级 incident，T+24h/T+72h/T+7d 继续探针。

## 调度流程

```text
Beat 每分钟
  -> select_due_live_races（只查小索引、最多 N 场）
  -> race_live.poll_event_source(event_id, source_key)
       -> 短事务：锁 tracking/control，校验 owner，领取 attempt token/generation，提交
       -> 无数据库事务/row/advisory lock：领取 host shared rate budget
       -> conditional GET / API batch cache
       -> identity + schema validate
       -> 短事务：写 observation，CAS 校验 claim/owner/current pointer
       -> reconcile + immutable revision + projection（shadow 不改公开投影）
       -> checkpoint next_poll_at，on_commit cache invalidate + metrics
```

selector 使用 `select_for_update(skip_locked)` 和 batch cap。领取事务提交后才允许网络 I/O，网络阶段严禁持有数据库事务、row lock 或 advisory lock；claim 有短 TTL，worker crash 后可由新 generation 回收。返回时 CAS 失败的旧响应只作证据，不得覆盖新状态。API 的当天批量响应以 host/date 为 cache key，一次请求可供多场赛事消费。单场 task 设置有界 retry、指数退避和 jitter；403/robots/条款问题为 non-retryable 并打开 circuit。

## 数据库、缓存和迁移

- 当前已实现 migration 为 `0033` 至 `0045`；`0041` 扩展非完赛状态 choices，`0042` 固定 TRA supplemental authority，`0043-0044` 增加 publication policy/allowlist 与发布快照，`0045` 增加 marker contract/evidence 和 verification incident。现有行默认 live mode off，不回填历史 results 为伪 revision。
- migration 不创建 tracking row、不启用 Beat、不切换页面 badge；所有行为由后续显式 flag 控制。
- 对现有 2025+ 赛事的 tracking 初始化使用 `initialize_race_live_events` 的严格 schema v1 manifest、SHA、approved commit、默认 dry-run、显式 apply 和独立 verify，不能在 migration 中隐式写入。apply 只建立 shadow baseline；同 manifest 精确 replay 零新增，任一 event 冲突整批回滚。
- 历史任务安全交接 manifest 必须先列出全部重叠赛事 event ID、2025+ 所有权、runner/container/lease、checkpoint、未完成目标、receipt 终态、待导入 bundle/chunks、`current_year_due`/new formal 清单、共享 host/限速状态和资源窗口；只有未被 STARTED receipt 或待执行批准 chunk 占用、且被明确移交的 event 才能切换为 `live` owner。
- 当前投影更新时校验 runner/result 数量、horse identity、同着/DQ 状态和人工锁；旧完整正式结果不能被较低来源降级。
- 数据库 check constraint 固定 `source_key=the_racing_api => result_authority=supplemental`；PostgreSQL deferred guard 继续验证 publication revision/event/source identity 一致。authority policy 变更只允许生成新审计 decision，不能原地提权 TRA。
- 事件页 cache key 包含 `event_id + canonical_revision_no/hash`；apply 后 `transaction.on_commit` 失效。Redis 故障只影响性能，不能导致错误状态晋级。

## 监控与告警

- Prometheus/结构化日志维度：region/source/host/phase/status，不把 URL 凭据、整页响应和人名原文塞入日志。
- Django admin/运营后台提供 live target、最新 observation、canonical revision、冲突、下一轮询和 kill switch 状态。
- 邮件/运营告警聚合到赛事级，避免每 3 分钟重复发送；同一 incident 只开一次，恢复后关闭。
- 每个正式窗口生成 acceptance summary：选中数、轮询数、暂定/正式延迟、冲突、手动介入、资源曲线和页面截图。

## 延迟证据

- 来源提供且已验证可信的更新时间时，记录精确 `source_available_at -> first_seen_at -> public_applied_at`。
- 人工观察到的外部可用时间单独标为 `manual_external_observation`，不能冒充来源机器时间。
- 无可信来源时间时，使用区间删失 `[previous_successful_poll_at, first_seen_at]`；采购和灰度门槛使用保守上界，不能把 `first_seen_at` 当作精确首次可用时间。
- 429/5xx/timeout 等失败轮询覆盖的区间进入 `polling_failure_delay` 单独报告，不混入上游来源延迟主 SLO；同时报告本站 `first_seen_at -> public_applied_at` 的确定延迟。

## 安全与内容边界

- 凭据只在 secret/env；Free proof 和生产 secret 分离，可轮换，不进入 traceback/artifact。
- SSRF 防护使用 source allowlist、固定 HTTPS host、禁止任意 redirect 到未批准 host、限制响应大小/类型。
- HTML/PDF parser 只提取客观字段；评论、评级、tips、赛后分析、图片/视频全部丢弃。
- source URL 可以后台追溯；公开 attribution 文案和 deep-link 必须符合来源条款，不能默认展示受限链接。

## 工作量、复用收益与成本

单工程师预计 6-10 个工程周，另加 2-6 周真实赛历观察时间：

| 工作包 | 工程量 | 主要复用 |
| --- | ---: | --- |
| 来源 proof harness + TRA Free | 4-6 天 | source cache、manifest、request budget |
| 数据模型/状态机/reconcile | 6-9 天 | RaceEvent/Runner/Result、事务/日志 |
| 调度/独立 worker/host limiter | 4-6 天 | Celery/Redis、queueing、历史锁原则 |
| 英国/HK 首批 adapter | 5-8 天 | 既有 parser normalization |
| 日/法/美 adapter 与许可差异 | 10-20 天 | 历史 fixtures；不复用抓取授权假设 |
| 页面/后台/标识 | 3-5 天 | 现有赛事页和 console |
| 集成、压测、监控、灰度 | 6-10 天 | 现有 health/log/runbook |

复用预计节约 15-25 个工程日，主要来自现有赛事身份、前台、runner/result 字段、术语展示、Celery/Redis、来源 parser fixtures 和历史链路的 manifest/锁/verifier 模式。不可节省的是实时延迟 proof、许可、状态机、revision audit 和五地区 shadow。

订阅初始成本为 £0；仅达到门槛并经用户批准后才增加 Basic £27.99/月（购买前复核）。现有服务器能否承载独立 worker 必须以 shadow 资源证据决定；若内存/CPU余量不足，另行评估小型独立运行节点，当前 plan 不虚构云成本。

## 主要风险

1. 来源使用/再发布许可比解析技术更可能阻塞日本、香港、法国、美国正式公开。
2. The Racing API 自称非官方且更新频率不保证，只能做 provisional 或交叉验证。
3. 赛事身份误配会把完整赛果写到错误赛事，是零容忍风险。
4. 现有覆盖式 result importer 不适合 revision，需要新链路但必须保持历史导入兼容。
5. 官方结果的“weighed-in/official”语义因地区不同，不能用统一页面文本猜测。
6. 退赛、同着、DQ、抗议、赛后数日纪律改判需要长期 correction probe。
7. 共享 Redis/broker 和宿主资源仍可能间接影响新闻；独立 queue 不等于物理资源隔离。
8. 真实重点赛事样本稀疏，观察周期可能比编码周期长，不能用普通赛事延迟替代全部验收。
9. 日本障碍分级赛 J-G1-3 的来源结构、完赛状态和样本密度可能不同于平地；它们默认计入原始目标，只有上述独立 proof 和用户批准的有效 deferred artifact 才能暂缓，不阻塞已达标的 G1-3/JpnⅠ-Ⅲ，也不能宣称日本全范围完成。
