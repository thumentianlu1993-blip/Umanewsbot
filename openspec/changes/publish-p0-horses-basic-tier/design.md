## Context

公开 `/horses/` 只有 12 匹人工发布马，而 P0 队列为 46,318 匹。发布层的唯一通道是后台逐匹 `transition_review_status`（services/horse_profiles.py:255-282），数据层（身份回填、滚动批次）已远超发布层规模。用户 2026-07-22 确认 BASIC 层公开门槛、批次审核后自动首发、日本先行三项决策。

既有事实（探索已核实）：发布状态字段为 `review_status`（draft/ready/published/hidden）；`auto_first_publish_enabled`（models.py:2819）是零引用死字段；公开索引 `views.py:3027-3055` 每页 24；徽章来自存储的 `completeness_status`；滚动批次地区 commit 在 `p0_horse_completion_commit.py:213-217` 复验失败即 raise，219-231 标记批次 committed；台账为 append-only `approvals_ledger.jsonl`；`mark_profile_completion_ready` 存在把 hidden 复活为 ready 的既有行为。

plan-eng-review（2026-07-22，2 P0 + 3 P1 + 3 P2 已全部纳入本设计）的关键修正：sync 路径 `_remember_profile_identity_keys` 按名称归属直接写 `horse_identity_keys`，与 fail-closed 回填共用同一扁平列表且 namespace 相同——门禁**不能**信任扁平 key 列表，必须引入核验 provenance。

## Goals / Non-Goals

**Goals:**

- 单一 BASIC 发布门禁服务，批次钩子与存量命令共用同一判据与同一写入通道。
- 自动首发只在批次地区 commit 幂等复验通过后发生；全链路审计（OperationLog + 台账 + checkpoint + run summary）。
- 存量经核验身份的马经 dry-run → 人工批准 → 分批 commit 发布。
- 前台对未完整马显示诚实的「资料补全中」徽章，完整档保留正面标签。

**Non-Goals:**

- 不启用 `auto_first_publish_enabled`（保持预留）；不做批量下线；不改变批次身份锁、xlsx 复审、串行窗口；不放松门禁换覆盖率；不改 `completeness_status` 的计算口径；不改造 sync 的 key 归属逻辑本身。

## Decisions

### 1. 身份核验 provenance：`horse_identity_verified_keys`

门禁的身份判据只读 `source_refs.horse_identity_verified_keys`（认可 namespace：netkeiba/nar/hkjc/sporting_life），**不读**扁平的 `horse_identity_keys`。verified 列表只由两条 fail-closed/人工批准通道写入：

1. 身份回填 commit（`p0_horse_identity_enrichment`）：写 `horse_identity_keys` 时同步写 verified key。
2. 滚动批次 commit（`p0_horse_production_apply`）：profile 经人工批准 artifact 成功写入后，其当前 identity keys 全部标记 verified。

sync 的 `_remember_profile_identity_keys` 继续只写扁平列表（供批次选择与匹配使用），不产生 verified 信任。存量可发布池因此精确等于回填核验的 2,789 匹（日本 2,462 + 香港 327）减去已发布 12 匹及后续批次增量；英国的 6,342 个 sync sporting_life key 与香港 58 个存量 sync key 不计入，留待后续核验通道。

### 2. BASIC 发布门禁判据

`evaluate_basic_publish_gate(profile)` 全部满足才可发布：

- 名称：`profile.display_name` 非空（既有回退链）。
- 地区：`racing_region ∈ P0_REGIONS`（france/hong_kong/japan/united_kingdom/united_states；`other` 与空值排除——`racing_region` 有 japan 默认值，"非空"判据形同虚设，必须按集合判定）。
- 身份：verified keys 含 ≥1 个认可 namespace 的 key，**或** `sire_text`+`dam_text`+`birth_date` 三字段齐全。
- 状态：`review_status ∈ {draft, ready}` 且 `hidden_at` 为空（曾 hidden 的马必须人工重新发布，隔离 `mark_profile_completion_ready` 的 hidden→ready 复活怪癖）；`published` 跳过计数。
- 锁定：`manual_lock_flags["auto_publish_blocked"]` 为真即阻断（人工 opt-out 键；设置方式记入 deploy_runbook 运维程序）。

### 3. 自动首发钩子在地区 commit 内、复验通过之后

插入点为 `commit_p0_horse_batch_region` 第 217 行之后、`mark_batch_manifest_status` 之前。复验失败先 raise，发布代码不会执行；串行窗口已退出，不延长 flock 持有。不设独立 `--publish` 阶段：批次 approve + xlsx 复审 + `--confirm-reviewed-artifact` 已是人工门禁。

发布对象 = 本地区 manifest profile_ids ∪ 本 completion run 新建 profile（`HorseP0Source.completion_run` 反查，`create_new` 行在 apply 时已回填 run FK）——否则批次新建马会永远滞留 draft（P1-2）。`completion_run` 为 None 时退回仅用 manifest ids 并跳过 run summary 写入（P2-3）。

`published_by` = 批次 commit 审核人（命令层已验证 active superuser），`note` 记录批次 ID/地区/artifact SHA。不设系统用户。

审计四通道：OperationLog（经 `transition_review_status`）、台账 `auto_first_publish` 条目（含 profile_ids 与计数）、`BatchRunState.artifacts["publish:<region>"]`、`completion_run.summary["auto_first_publish"]`（复验通过后二次 save）。

失败语义（P1-3）：逐匹 try/except 汇总 errors；**存在 errors 时写入 `state.errors`、不记录完成的 publish stage 并 raise**——批次不得带着缺失的 publish artifact 进入 `committed` 终态（多地区批次同样要求每个地区都有完成的 publish stage 才能进入终态）。由于同 artifact 全量重 commit 会被快照漂移检查 fail closed（既有行为，不改动），恢复走独立的 `--retry-publish` 阶段：只重跑发布步骤（要求该地区已有复验通过的 commit artifact），成功后补齐 publish stage、清理 state.errors、补写台账与 run summary，并在全部地区就绪后推进 committed 终态。

`retry_region_publish` 必须核验 commit artifact 中的 `idempotent_verification.passed == True`——commit 的 completed_stages 在复验判定前写入，仅凭 stage 存在不能证明复验通过（review P1-1 修正）。

### 4. 存量发布走与身份回填相同的门禁形态

`publish_p0_horse_profiles --dry-run/--approve/--commit`：dry-run 输出候选 JSONL、阻断原因直方图、SHA-256 manifest、metrics_before，默认零写库；commit 要求 manifest 重算哈希 + active-superuser reviewer-id；按地区分批、单事务 ≤500 profile；metrics_after；幂等重跑全部 skipped。候选范围为 `review_status ∈ {draft, ready}`、`hidden_at` 为空、未锁定的 profile。

### 5. 徽章以 `completeness_status` 为唯一事实源

`HorseProfile.public_completeness_badge` property：完整二代血统/完整马匹资料返回既有 display 标签，其余档位返回「资料补全中」。模板两行替换（index 卡片 `horse_index.html:31` + detail hero `horse_detail.html:15`）。不新增存储字段、无迁移。

### 6. 规格 supersede 的边界

MODIFIED `马匹资料审核控制公开可见性`（审计场景扩展为三种发布路径 + hidden/曾 hidden 不自动发布）与 `首批公开验收必须由人工发布触发`（首批验收已于 2026-07-21 完成，新增"验收后启用受门禁约束的自动首发"场景替代"自动发布能力仅预留"的 SHALL NOT）；BASIC 门禁与徽章为 ADDED。Purpose 段"只有管理员审核发布后才进入前台"的措辞在 spec-sync（tasks 7.4）时同步更新。

## Risks / Trade-offs

- [错误身份马被公开发布] -> 三层缓解：verified key 只来自 fail-closed 回填或批次批准 commit；门禁 namespace 白名单；批次流 xlsx 人工复审 + 存量流 artifact 人工审。sync 名称归属 key 明确排除。
- [46k 公开后的索引性能] -> `horse_status_region_idx` 覆盖过滤，COUNT 廉价，排序 filesort 可接受；留监控注记，必要时加复合索引。
- [复验通过与发布之间的漂移] -> 发布前实时重估门禁（hidden/hidden_at/锁定/verified 判据），不靠快照。
- [审计量] -> OperationLog 增加 ~46k 行（长期分摊），可忽略；逐匹留痕是审计特性而非负担。
- [规模轨迹] -> 日本 ~116 批（100/批）；前 5 批零失败后 `--limit-per-region` 提到 250，不跨地区并行。

## Migration Plan

1. 实现 provenance 写入（回填 + 批次 apply）、门禁服务 + commit 钩子 + 存量命令 + 徽章，全量测试（含复验失败零发布、hidden/hidden_at/锁定阻断、create_new 覆盖、幂等）。
2. 独立 code review 修复后合并 main。
3. 生产执行（分步用户授权）：备份 → 停 beat/worker → `HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=true` 重启 → 首个日本批次全链路（prepare 触网）→ 核验自动首发 → 存量 dry-run → 人工批准 → 按地区 commit → metrics → 恢复服务。
4. 回滚：下线为后台逐匹转 hidden；代码回滚不影响已发布状态（发布是数据不是 schema）。

## Resolved Questions

- BASIC 门禁非身份分支按 sire_text+dam_text+birth_date 三字段实现（名称已由 name 判据覆盖）——用户 2026-07-22 确认 BASIC 层定义时采纳。
- `published_by` 用批次审核人不设系统用户——计划阶段用户批准。
- `auto_first_publish_enabled` 保持预留不启用——计划阶段用户批准。
- 门禁身份判据只信 `horse_identity_verified_keys`，sync 归属 key 不计入——plan-eng-review P0-1 修正（2026-07-22）。
- 发布对象含批次 create_new 新建马（completion run 反查）——plan-eng-review P1-2 修正（2026-07-22）。
- 发布失败阻断批次 committed 终态——plan-eng-review P1-3 修正（2026-07-22）。
