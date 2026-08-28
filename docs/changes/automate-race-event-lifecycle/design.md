# 赛事日历自动更新与赛事生命周期设计

## 1. 当前真实数据流

### 1.1 赛事总账与展示

```text
导入/人工候选
  -> RaceEventDataCandidate
  -> apply_data_candidate()
  -> RaceEvent + RaceEventRunner/Result/HistoryWinner
  -> post_save RaceEvent
  -> invalidate_public_race_cache()
  -> public_race_calendar / public_race_detail
```

`RaceEvent` 保存：

- instant：`race_datetime`（Django `USE_TZ=True`，数据库按 aware/UTC 语义）；
- 当地展示：`timezone_name/local_date/local_start_time`；
- 产品状态：`status`；
- 等级与重点：`normalized_grade/priority/is_featured`；
- 结果确认：`result_confirmed_at`；
- 人工锁与来源摘要：`manual_lock_flags/source_refs`。

`is_key_race` 已定义为 P0/P1 或 `is_featured`。公开日历的“重点”tab 也按此条件查询。

### 1.2 现有准实时链路

```text
Celery Beat 每分钟
  -> select_due_race_live_events_task（普通 worker）
  -> claim_due_race_event_live_tracking(select_for_update skip_locked)
  -> poll_race_live_event_task(queue=race_live)
  -> race_live_worker
  -> provider observation（append-only）
  -> RaceEventRevision + items + evidence
  -> publication policy/allowlist
  -> RaceEventResult projection
```

已有能力：

- `RaceEventProjectionControl` owner generation/CAS；
- `RaceEventLiveTracking` claim generation、attempt token、TTL、checkpoint、失败计数；
- `RaceLiveHostBudget` 限流与 circuit；
- observation hash 唯一约束、revision 序号/内容唯一约束；
- provisional/official/corrected 权威规则；
- racecard 参与者 merge 不把来源遗漏解释为退赛；
- public read policy 可隐藏未获准 live revision；
- QQ `(article,target)` 唯一约束与发送 claim。

生产文档最近确认 scheduler/monitor/enabled regions 均关闭；event 924 是唯一公开暂定灰度，
TRA 仍为 supplemental。该记录是仓库已保存的生产证据，不代表本轮重新核验了服务器运行态。

### 1.3 新闻链路

```text
抓取 -> 翻译 -> score_article_for_automation
  -> rewrite -> validate_rewrite（内容、术语、重复）
  -> PUBLISH_READY
  -> auto_publish_batch / region publish window
  -> publish_article_automatically
  -> on-demand QQ delivery（唯一约束）
```

现有关联 `associate_articles_for_event()` 只处理已经公开的新闻。标题/摘要命中正式名/别名可
建 `AUTO` link（95），正文命中只建 `CANDIDATE`（70）；它不提取字段，也不参与发布放行。
仅名称命中无法安全驱动赛事变更。

### 1.4 公开读取

- 日历：直接按 `RaceEvent.status` 过滤/标注；只在 `finished` 时展示确认 winner；
- 详情：`RaceEvent.status` 显示赛事状态，live revision 另显示暂定/正式/更正；
- 新闻详情 teaser：另有 `status=scheduled` 且日期未来的筛选；
- 首页赛事区域属于后续独立 change，本轮不修改；
- 赛事 cache 当前只缓存 sitemap 数量和年份，`RaceEvent` save/delete 会清理；页面正文无
  长缓存，但 bulk update 不触发 signal，生命周期服务必须显式调用统一 invalidator。

## 2. 设计原则

1. 不增第二个赛事总账。
2. 不把 live tracking 扩成所有赛事的通用发生状态。
3. `RaceEvent.status` 负责赛事是否已发生；revision 负责结果权威。
4. 时间推进与来源同步是两个动作，可在同一 orchestration run 中分别成功/失败。
5. 所有写入先锁单场赛事，随后按固定锁序处理 operational/provenance/audit。
6. scanner 只选有界 due 行；不对全表高频轮询。

## 3. 建议数据模型

### 3.1 `RaceEventLifecycleControl`（新增，一对一）

这是运行控制面，不是第二状态机：

- `event`
- `mode`: `off/shadow/enforce`（dry-run 是一次性只读命令，不是持久 Beat mode）
- `next_refresh_at`
- `schedule_generation`
- `last_attempt_at/last_success_at`
- `last_result_code/last_error`
- `last_source_key`
- `refresh_profile`（P0/P1）
- `consecutive_failures`
- `claim_token/claim_generation/claim_expires_at`
- `manual_pause_reason`

索引：`(mode,next_refresh_at)`、`(event,schedule_generation)`。迁移不自动启用既有行。

### 3.2 `RaceEventLifecycleTransition`（新增，append-only）

- `event`
- `from_status/to_status`
- `reason_code`
- `effective_at`
- `source_authority/source_key/source_url`
- `trigger_task/run_id`
- `schedule_generation`
- `record_kind`: `proposal/applied`
- `dedupe_key`（unique）
- `based_on_proposal`（applied 可引用既有 shadow proposal）
- `metadata`

proposal key 与 applied key 必须不同：

```text
proposal:<event>:<generation>:<action>:<boundary>
applied:<event>:<generation>:<action>:<boundary>
```

同 generation 可多次执行 shadow，但只有一条 proposal；首次 enforce 在更新 `RaceEvent.status`
的同一事务创建 applied 行，随后 enforce 重放命中 applied key。不得把 append-only proposal
改写成 applied。

### 3.3 `RaceEventFieldAuthority`（新增）

每个字段目标每字段唯一：

- `event`
- `subject_type`: `event/participant`
- `subject_key`: event 使用固定 `event`；participant 使用
  `RaceEventParticipant.stable_key`
- `field_name`
- `authority_level`
- `source_key/source_url/external_id`
- `confidence`
- `observed_at`
- `article/candidate/revision`
- `value_sha256`

唯一约束为 `(event,subject_type,subject_key,field_name)`。参赛马字段只能绑定
`RaceEventParticipant`；赛前来源须先通过 provider-bound runner identity 创建/匹配 participant，
再由 racecard revision 投影 legacy `RaceEventRunner`，不以会被 replace 的 legacy row PK
作为 subject。participant merge 需要显式 identity review/alias，stable_key 不就地改写。

写入时 `select_for_update` 比较。更高权威可升级；同等级不同值转冲突；低等级拒绝；相同值
可补充 evidence 但不重复改字段。

### 3.4 `RaceEventFieldChange`（新增，append-only）

保存规格要求的原值、新值、来源、置信度、任务、新闻、模式和拒绝/应用结果。原/新值用
规范 JSON；对可能含敏感/大正文的值只保存最小结构化字段与 hash。

### 3.5 `RaceNewsImpactAssessment`（新增，一篇可有多个版本）

- `article`
- `classifier_version/content_sha256`
- `affects_race_details`
- `matched_event`
- `event_type`
- `extracted_changes/evidence`
- `confidence/source_authority`
- `decision`: `not_impacting/eligible/candidate/review_required/rejected/applied`
- `reason_codes`

唯一约束：`(article,classifier_version,content_sha256)`。

### 3.6 复用而不新增

- 出马表/赛果继续用 `RaceEventParticipant/Revision/RevisionItem` 和 legacy projection；
- 人工候选继续用 `RaceEventDataCandidate`；
- 新闻关联继续用 `ArticleRaceLink`，assessment 通过后才创建/升级；
- task 日志继续用 `TaskExecutionLog`，运营动作继续 `OperationLog`；
- provider 限流继续 `RaceLiveHostBudget`，不建另一 HostBudget。

## 4. 核心服务

### 4.1 纯决策函数

`decide_race_lifecycle(event, now) -> Decision`：

- 输入必须是 aware `now`；
- 校验 IANA 时区、instant 与当地字段一致；
- 返回 `noop/transition/error`，不访问网络；
- cancelled 不前进；
- postponed 只等待新 schedule generation；
- official/corrected 不回退；
- 无时间使用当地次日边界；
- 使用显式 reason 和 effective time。

### 4.2 原子应用

`apply_race_lifecycle_decision(event_id, expected_generation, now, mode)`：

1. `transaction.atomic`；
2. `RaceEventLifecycleControl.select_for_update`；
3. `RaceEvent.select_for_update`；
4. 核对 generation/claim；
5. 重算 decision，防 TOCTOU；
6. shadow 只写 proposal；enforce 更新 `RaceEvent.status` 并写独立 applied transition；
7. 按 record kind 的 dedupe key/唯一约束处理重放；
8. 计算下一次刷新并释放 claim；
9. `transaction.on_commit(invalidate_public_race_cache)`。

### 4.3 显式纳管与资格同步

新增 `reconcile_race_event_lifecycle_controls` 管理命令/服务：

1. 默认 `--dry-run`，零数据库写入、零 Celery dispatch；
2. 输入显式 manifest SHA，manifest 冻结 event IDs、`is_key_race` 资格快照、priority、
   visibility、status、local date/time/timezone、region、目标 mode 与 allowlist；
3. `--apply --manifest-sha256` 才按 event ID 分页（每页最多 500）幂等
   `update_or_create` control；重复 apply 不重复建档或 bump generation；
4. 只有 published、`is_key_race`、允许 region/event、非 cancelled 才可进入 shadow/enforce；
5. priority/is_featured/visibility/status/timezone/date/time 变化由每日 bounded reconciler
   对“已有 control＋manifest event IDs”重算。失去资格、取消或人工暂停即 `mode=off`；
   schedule 变化才 bump generation 并重算 `next_refresh_at`；
6. 不扫描全量 RaceEvent 自动扩容。新增赛事必须生成新 manifest 并重新授权纳管；
7. manifest/reconciler 记录 eligible/ineligible/created/updated/disabled/replayed 计数。

无 control 始终默认不启用；这是迁移安全边界，不是遗漏。

### 4.4 扫描与任务边界

新增普通 worker 任务：

- `scan_due_race_event_lifecycle_task`：Beat 每 5 分钟；每批最多 100，按
  `next_refresh_at,event_id`，`select_for_update(skip_locked)` claim；
- `advance_race_event_lifecycle_task`：纯时间推进和审计，不联网；
- `refresh_race_event_preplace_task`：按 provider/地区/赛日合并，并生成 field/racecard
  candidate；阶段 B 才启用。

保留：

- `select_due_race_live_events_task` 每分钟作为赛果选择器；
- `poll_race_live_event_task` 只在 `race_live` queue/race_live_worker 运行；
- 普通 worker 不直接抓准实时赛果；
- race_live_worker 不跑全表/新闻/生命周期扫描。

阶段 A 不启用任何新 provider，也不初始化 live tracking。它可以在现有赛果任务之前或之后
独立更新 `RaceEvent.status`；race-live 接受 `scheduled/running/finished`，不会被破坏。

持久 scanner 只支持 shadow/enforce 并写 operational claim。一次性
`reconcile... --dry-run`/`advance... --dry-run` 是严格零写、零 dispatch 的验收入口。
不设置“Beat dry-run”，避免每 5 分钟重复派发同一批。

### 4.5 失败恢复

- claim TTL 建议 4 分钟，任务 soft/hard timeout 120/150 秒；
- 网络任务最多 3 次 exponential backoff + jitter；
- 生命周期纯 DB 任务最多 2 次仅重试瞬时 DB 错误；
- provider 429/403/circuit 分地区隔离，不阻塞其他来源；
- 连续失败达到阈值只暂停该 provider/赛事资料刷新，不暂停时间推进；
- expired claim 可被下轮回收；
- task ID 不是幂等键；transition 幂等键由 record kind、event、generation、action、
  effective boundary 组成。

## 5. 时间与时区

地区规则复用现有 race-live 校验：

| 地区 | IANA 时区 |
|---|---|
| 日本 | `Asia/Tokyo` |
| 中国香港 | `Asia/Hong_Kong` |
| 英国 | `Europe/London` |
| 法国 | `Europe/Paris` |
| 美国 | 每场已审核 `America/*`，不得设全美默认 |

`TIME_ZONE=Asia/Shanghai` 和 `CELERY_TIMEZONE=Asia/Shanghai` 只影响应用/Beat 表达，不参与赛事
边界。DST 由 `zoneinfo` 处理；当地日期＋当地时间组合时：

- ambiguous time：要求来源携带 offset 或进入人工审核；
- nonexistent time：拒绝写入；
- source aware instant 转换后必须与 `local_date` 一致；
- 改时同时更新 `race_datetime/local_start_time`，并写字段审计/generation。

固定地区精确拒绝任何“有效但错误”的 zone，例如香港 `Asia/Tokyo`、英国 `Europe/Paris`、
法国 `Europe/London`。美国除 `America/*` 前缀外，还必须命中该 event 纳管 manifest 中已审核
的具体 zone；不能仅凭前缀自行更换。

## 6. 来源覆盖矩阵

“可解析/历史导入”不等于“已批准自动生命周期生产”。初始矩阵：

| 地区 | 现有来源 | 出马/时间/骑师/闸位/退赛 | 赛果 | 当前允许自动生产 |
|---|---|---|---|---|
| 日本 JRA | JRA-VAN/JV-Link，经 `jrvltsql` 落独立 staging；JRA 官方公告 | `RA/SE/AV/JC/0B15` 可覆盖赛程、出马与临场变化；需真实 live proof | `0B12/HR` 可作官方确认候选 | 用户已核实限速使用边界；阶段 B/D 仍需技术 proof 和独立启用授权 |
| 日本 NAR/JPN1 | NAR 官方 CSV，或经批准的地方競馬DATA/NV-Link | 官方 CSV 提供未来已发布出马表和约 2 分钟当日更新；许可需冻结 | 官方 CSV 含赛果/払戻候选 | 与 JRA provider/event id 分离；阶段 B/D 需新 proof/授权 |
| 香港 | TRA Pro 主结构化源；HKJC 官方复核 | TRA Core 宣称完整覆盖，HKJC racecard/排位能力较强 | TRA provisional；HKJC official | 新 TRA 扩围和 HKJC 自动复核均需独立 proof/授权 |
| 英国 | TRA Pro；BHA 官方复核；Sporting Life internal reference | Pro 最远 T-7，临近日约 15/3 分钟更新；Sporting Life 只供内部交叉核验 | TRA supplemental provisional；官方来源确认 official；Sporting Life 无结果权威 | event 924 以外需按地区扩围 proof；内部参考不进入 projection |
| 法国 | TRA Pro；France Galop 官方复核；ZEturf internal reference | P0 G1 理论落入 global Group 范围，但需逐场验证；ZEturf 只供内部交叉核验 | TRA provisional；France Galop official；ZEturf 无结果权威 | 阶段 B/D 需新 proof/授权；内部参考不覆盖 France Galop |
| 美国 | TRA North America add-on；Equibase 人工/另签；HRN internal reference | add-on 有 meets/entries/changes；HRN 只供内部发现和部分结果参考 | add-on results provisional；Equibase 获授权数据可复核；HRN 无结果权威 | 禁止 Equibase scraper/stealth；HRN 不进入 projection |

TRA Free 的现状是：认证/端点/schema proof 和 event 924 有界 shadow/provisional 灰度成功，
但不是全地区全面批准；不能产生 official。法国匹配仍有 fail-closed 缺口，其他地区也需逐场
身份、条款、字段完整性和观察窗口。

来源 fallback：

1. 同 provider 重试/cache；
2. 同地区已批准次级来源生成可应用候选；
3. 官方新闻/公告；
4. Sporting Life/ZEturf/HRN 只生成内部参考观察，不属于可应用 fallback；
5. 其他可信媒体仅人工候选；
6. 全部失败时仍按时间推进状态，结果保持 pending。

### 6.1 商业 API 候选

商业来源的详细调研、公开价格、许可风险和采购问卷见
`commercial_api_research.md`；地区分流与 GitHub 候选审计见
`regional_source_research_20260725.md`。设计允许将付费来源接入阶段 B/D，但“付费”不改变 authority：

- The Racing API 是当前最适合低成本 proof 的聚合 API，公开 Pro 价格 £99.99/月、北美
  add-on £49.99/月，覆盖英国、香港、全球重点赛与北美；其条款明确不是官方来源，因此默认
  只能作为 `verified_professional_api/supplemental`。
- 日本 JRA 采用 JRA-VAN + `jrvltsql` 候选，价格 ¥2,090/月。用户已核实限速使用边界；
  技术上仍必须使用独立 Windows collector/staging，并且不能把 JRA 覆盖泛化到 NAR/JPN1。
- Equibase 可按场或按月取得机器可读美国 chart，优先用于赛后人工/获授权 official proof，
  不替代赛前来源。其网站明确禁止自动 scraper 和未经许可再发布，因此 GitHub scraper
  不进入生产候选；自动接入只允许另签 Data Sales API 或使用 TRA North America add-on。
- SIS、Podium、BetMakers、Racing and Sports 属询价型企业候选；未取得逐字段报价、SLA、地域
  与中文公开展示许可前不得进入 registry。

authority 必须绑定 `(provider,region,field_name,result_phase,provider_contract_version)`，不能把一个
供应商在某地区的官方合同泛化到其全球聚合数据。

爱尔兰虽属于 TRA Core 覆盖，但当前 `RacingRegion`、时区、P0 分母和公开页面均未建模。本
change 不接入爱尔兰，不得映射成英国或 `other`；未来必须独立变更模型、迁移、`Europe/Dublin`、
身份、页面、测试和 rollout。

### 6.2 内部参考源隔离链

内部参考链复用三个现有 parser 的解析和安全请求能力，但不复用
`import_race_event_detail_candidates --apply`：

```text
冻结 event manifest
  -> source-specific parser/cache
  -> reference schema validator
  -> identity match（matched/unmatched/ambiguous/source_only）
  -> RaceReferenceCollectionRun
  -> immutable RaceReferencePayload
  -> per-run RaceReferenceReceipt
  -> staff-only read-only admin/report
```

建议新增三个模型：

- `RaceReferenceCollectionRun`：记录 provider、地区、manifest、请求/cache/覆盖/错误和 artifact；
- `RaceReferencePayload`：按 source/observation/payload hash 去重的不可变结构化来源事实；
- `RaceReferenceReceipt`：每个 run 的 payload membership、event 匹配证据、partial/gap 与分类版本。

模型本身不含 publish/apply 状态；服务层禁止调用 data candidate、race-live projection、
news/QQ。公开 view/query/template/sitemap 不读取这些模型，admin 无 add/change/delete/promotion。
相同 payload 跨 run 复用 payload 并新增 receipt；内容变化新增 payload；歧义不绑定 event；相同
payload 后续重新匹配只新增 receipt。

第一实现单元 B0.1 只提供 manifest-bound one-shot collect、离线 record 和 report，不注册
Celery/Beat/task/queue。现有 parser 仅按 `finished` 赛后结果使用；赛前 route 属后续独立 proof。
生产依次经过离线 fixture、one-shot 网络 collect、小范围内部 record 和 7 个逐日 one-shot
观察；任何阶段都没有公开发布步骤。精确 schema、manifest、HTTP 限制和并发合同见
`internal_reference_sources.md` 和 `phase_b_reference_implementation_handoff.md`。

### 6.3 JRA collector snapshot 合同

JRA-VAN authority 的主体是合同来源本身，`jrvltsql` 版本仅作为 provenance。Windows collector
不得直接连接 Umanews 生产数据库。唯一传输方式为 Umanews 通过受限 SFTP-only 账号主动拉取的
不可变 Ed25519 签名 snapshot：

- envelope 固定记录 schema/snapshot/provider/contract、collector ID/git/build SHA、活动
  fencing token、upstream spec/high-watermark、源时间、抓取时间、计数、payload/前驱 hash；
- payload/manifest 写入临时目录并 fsync，签名、原子 rename 后最后写 `COMPLETE`；
- Umanews 只接受活动 collector/fencing token、允许的 build/schema/contract、签名、hash、marker
  全部通过的连续 snapshot；乱序、缺前驱或漂移 fail closed；
- 每个 upstream spec 的消费水位只在业务事务提交后推进，snapshot ID + payload hash 唯一重放；
- collector 轮换先在 registry 签发更高 fencing token，旧 token 立即失效；
- payload 保留 30 天；manifest、消费 receipt 和字段审计长期保留；
- 赛日 RPO 5 分钟/RTO 30 分钟，非赛日 RPO 24 小时。超时告警但不阻断时间状态推进；
- rollback 先关闭 provider kill-switch、撤销 token/key、停止拉取；已应用的高权威事实只能通过
  人工批准 reverse candidate 回退。

JRA `0B12/HR` 的具体状态码在真实 proof 前不预设。registry 必须逐项冻结
`record_type + raw_status + sequence/correction marker -> provisional|official|corrected`：
三名、五名、字段不全或未知阶段只能 provisional/pending；仅显式全马最终 marker 可 official；
official 后出现的明确修正 marker 只能前进为 corrected。未知 marker 一律 fail closed。
NAR CSV 使用独立 provider contract 和 marker 映射，不能继承 JRA 规则。

## 7. 新闻门禁实现位置

新增 `assess_race_detail_impact()`，在成功翻译后、普通评分决定前运行；它不跳过
`validate_rewrite()`。建议流程：

```text
translation success
 -> impact assessment + unique race identity
 -> score（impact 可覆盖 score/review mode 的软部分）
 -> rewrite/validation（全部硬 blocker 仍执行）
 -> special publish pool（独立小配额）
 -> publish transaction commit
 -> on_commit dispatch candidate apply
```

`is_ready_for_auto_publish` 拆为可解释 hard readiness 与 normal policy。特殊池仍要求：

- `PUBLISH_READY`；
- 无 blocker；
- source production approved；
- assessment eligible 且内容 hash 未漂移；
- unique race identity 未漂移；
- 未发布/未撤回/未 duplicate。

发布事务使用 `select_for_update` 重验 assessment/article。QQ 仍经
`ensure_qq_push_deliveries` 和现有 category/target/importance 门禁；`racecard_update` 默认
不自动 QQ，除非以后独立授权。

现有 reason-code 的 hard/soft/not-blocking 精确映射以 `spec.md` 9.4 为合同；实现必须使用
显式 allowlist 绕过 soft code，未知/新增 blocker 默认 hard。`region_not_allowed`、
`source_not_allowed`、`term_candidate_backlog` 均不得绕过。

## 8. 字段提取与应用

允许结构化字段：

- `race_datetime/local_date/local_start_time`
- `status=postponed/cancelled`
- runner `barrier/jockey_name/running_status`
- participant add/remove（必须 provider-bound identity 或人工审核）

禁止新闻直接写：

- official finish position / `result_confirmed_at`
- 未列入 allowlist 的赛事基础资料；
- 由名字模糊推断的马匹身份；
- 高权威已确认字段。

自动应用范围初始建议仅限官方公告、confidence >=95、唯一赛事、无冲突的
`scratch/jockey_change/barrier/time_change/postponed/cancelled`。其他都进候选。

## 9. 后台

优先扩展现有 console `race_event_form.html` 和 Django Admin：

- 当前赛事状态、结果 phase；
- 下次刷新、最近 attempt/success/result/error；
- 当前 source route/authority；
- 最近 20 条 lifecycle transition；
- 最近字段变化/冲突；
- 延期/取消/退赛影响摘要；
- 新闻 impact assessments 和待审 candidates。

建议增加：

- “立即刷新赛前资料”：仅 `stable.change_raceevent` 且额外 staff 权限；只 bump generation、
  claim 后入队，不在 HTTP 请求内联网；全量 OperationLog。
- “重新拉取赛果”：更高权限；仅已有 live control/approved source，复用 race_live queue、
  CAS 和限流；不允许改变 publication mode。

两个动作都必须拒绝 active claim、人工暂停、未批准来源和错误状态；不得绕过 provider budget。

## 10. 查询与性能

- scanner 只查 `LifecycleControl(mode,next_refresh_at)` 索引；
- 每批 100，使用 `select_related(event)`，不预取大 JSON/revision items；
- 每个 event 的锁内查询保持常数；最近审计由后台按需分页；
- provider 同一赛日请求合并，结果按 event identity 分发；
- 不在页面逐赛事调用 live read：继续使用现有 batch `resolve_race_live_public_reads`；
- 增加 query-count 测试：100 场扫描选择不超过 8 查询，应用阶段每场常数上界；
- 不使用 `RaceEvent.objects.all()` 高频扫描。

## 11. 分阶段交付决定

推荐拆成四个可独立发布、独立开关、独立回滚的实施单元；本目录作为总设计基线：

### A：生命周期自动推进

只实现控制面、纯时间决策、审计、后台只读信息和 dry-run/shadow/enforce。不上新来源，不改
新闻门禁，不打开 race-live。先解决“旧赛事仍赛前”根因。

### B：赛前结构化资料同步

逐地区完成 source proof 后接入出马/时间/骑师/闸位/退赛/延期；复用 racecard revision、
HostBudget、candidate 和 authority。

阶段 B 先拆出 B0.1：Sporting Life、ZEturf、HRN 的现有赛后 parser 仅形成内部 reference
run/payload/receipt。B0.1 可在不接入公开字段同步、不增加调度的情况下独立实现、review、
关闭部署和逐日 one-shot 观察；B0.1 数据不得成为 B 的字段 authority 或 D 的结果 revision。

### C：赛事影响新闻联动

独立迁移/分类器/特殊池/候选回写；先 shadow 分类，再小范围 enforce。不开新赛果来源。

### D：赛中与赛后赛果

复用 race-live selector/worker/revision；只对已批准 event/region 开启。时间推进来自 A，
结果权威来自现有 revision。

唯一调度所有者仍是现有 `select_due_race_live_events_task`：

1. lifecycle scanner 不 dispatch `poll_race_live_event_task`；
2. T+0 selector claim 后，race-live runner 只 CAS
   `racecard_ready -> awaiting_result`，释放 claim，并写
   `next_poll_at=race_datetime+3min`，本次不读取 registry、不调用 transport；
3. T+3 selector 再 claim，才允许首次网络调用；
4. 现有初始化 manifest 必须升级/校验该 `first_result_poll_not_before` 合同；旧 tracking
   没有该字段时从 authoritative `race_datetime+3min` 计算，不能取当前时间；
5. 无时间赛事的 A 阶段只创建“result backfill candidate”。只有后续已批准 provider route
   将其初始化为 live control 后，才由同一个 selector dispatch；
6. 去重继续使用 owner generation＋claim generation＋attempt token；不新增第二 dispatch key。

event 924 的已存在 observation/publication 不迁移、不重跑；只对未来 `racecard_ready` claim
应用 T+3 合同，并保留其既有 public policy/kill-switch。

不建议一次性完成四阶段：来源 proof、新闻治理和 live result 的回滚面不同。用户若G1 范围确认，
默认授权范围应先解释为阶段 A；B/C/D 各自在开始测试前再次确认精确来源和开关范围。

## 12. 预计文件范围

阶段 A 预计：

- `server/stable/models.py`
- 新 migration
- `server/stable/services/race_event_lifecycle.py`
- `server/stable/tasks.py`
- `server/app/settings.py`
- `server/stable/admin.py`
- `server/stable/views.py`
- `server/stable/templates/stable/console/race_event_form.html`
- `server/stable/services/race_event_public_cache.py`
- lifecycle 纳管 manifest/管理命令与 rollback manifest 工具
- 新 lifecycle 测试文件
- Compose/`.env.example` 仅增加默认 off flags（测试先行）

阶段 B0.1 预计新增三个 reference models/migration、`race_reference_sources.py`、四个管理命令、
只读 admin、safe HTTP 上限，并抽取由历史 CLI 共用的三个 parse-only runtime parser；不修改
Celery/Beat/worker/Compose。阶段 B/D 后续预计
触及 `race_events.py`、`race_live_*` 与 provider registry；阶段 C 预计触及 `automation.py`、
`validation.py`、`publishing_windows.py`、news models/tasks/admin。
具体实现前必须再次做 hunk overlap preflight。

## 13. 2026-08-28 目标驱动的统一实现定稿

用户本轮明确要求完成整条自动生命周期，并允许覆盖本文早期按阶段逐次确认的设计门禁。实现因此统一为：

- future discovery + standing policy 自动纳管未来公开赛事；
- `race_sync_v2` projection owner 独占字段投影，claim/complete 以 generation/token/plan SHA 做 CAS；
- licensed API、官方导入、可信第三方使用 300/200/100 确定性仲裁；
- race time/racecard 最慢 12 小时一次，临赛加密；result 自 T+3 起轮询并保留 7 天 correction watch；
- lifecycle 在 T/T+30 推进，postponed 和无时间赛事不误推；
- immutable revision 保存原始与更正赛果，公开页统一显示“赛果”。

生产门禁没有被代码实现替代：全部新开关默认关闭、容量默认 0，最终部署仍需绑定合并 revision 的确认。
完整实现、dry-run 和发布说明见 `race_data_lifecycle_implementation_20260828.md`。
