# 四地区分级赛参赛马回填 Rollout

## 当前检查点（2026-09-01，取代下方历史检查点）

- worktree：`/Users/mentianlu/.codex/worktrees/staging-france-2023-foundation/umanews`
- branch：`codex/full-graded-horse-export-runtime`；从当时 latest `origin/main@71eafb65…` 创建，主工作区与旧 dirty
  export worktree 均未修改或重置。
- France 2023 selected stable-ID 批次已经 5/5、19 GET `COMPLETE`，并已将 5 horses / 60 races /
  67 results-histories / 5 variants 写入 External staging；canonical identity/profile/public apply 仍为 0。
- execution as-of 已推进到 2026-09-01：12,048 total / 11,939 due / 10,795 bulk-2005+ /
  1,144 pre-2005 / 109 not_due。calendar/source/bulk readiness 均已重放，未发现 8 月 31 日或 9 月 1 日新增 due target。
- 官方 OpenAPI 仍为 1.4.4，full SHA `0033643fcca4301889098fe6dcda021beb840207880f848a25b6153208a87df7`；
  standard selected schema 已从历史 `HorseStandard` 漂移为 `Horse`。当前 selected path/schema SHA 为
  `910e5ccc…14ba / cc7fc55e…9173`，review artifact SHA 为 `d505ad64…4200`。
- bulk 查询已按 provider 明确建议修正为“一个地区、一个自然日”：31,656 个 date ranges、88 个 region-year batches，
  plan/manifest SHA 为 `49f1bdbe…982a / 33359936…2d7`。旧 32-batch 年度范围 plan 与其 G3 全部只作历史证据，不得执行。
- 新 plan 的协议 fail-closed ceiling 为 316,560 GET（每个地区日最多 10 页）；正常预期约 31,656 GET。
  client 固定单并发、4 req/s、逐页 checkpoint，proof 到期或 ceiling 风险时 safe-stop，再以 fresh proof 从下一页 resume。
- 本轮用户已明确其他阻塞清空并要求在本会话持续完成；仍需在每次生产窗口现场重验 shared lock、服务、资源、
  flags、队列和 registry，不能把这项授权替代运行态证据。

## 历史检查点（2026-08-31）

- 日期：2026-08-31（Asia/Shanghai，以下为历史记录）
- worktree：/Users/mentianlu/.codex/worktrees/export-graded-race-horses-2000-current
- branch：codex/export-graded-race-horses-2000-current
- 初始 baseline：origin/main@a063ecf985539fc2d82a27170c7d634e0f7e5fc8（历史记录，不代表当前生产 revision）
- 主工作区：/Users/mentianlu/Code/umanews，存在大量用户改动，本 change 不触碰
- 当前阶段：G1 已满足；proof-only PR #125/#126 已部署，Montjeu N1 已执行累计 3 GET 并以
  `provider_partial` 收口；pre-2005 来源路线已离线收敛，但 source/correction approval、四地区批量、
  identity/module review 与生产 apply 均未批准。
- Montjeu N1 更新：proof-only 代码已部署，真实 paid path 已执行。search/results 两个 GET 均为 200，但
  provider career 未给出唯一 1999 Arc occurrence，故以 `provider_partial`、本轮 2 GET、累计 3/16、
  DB writes=0 收口；这不构成批量、staging、canonical apply 或发布授权。

### 当前生产协调硬门禁

- 2C/8G 扩容后的完整服务态 `MemAvailable=5.31–5.38 GiB`，超过 1,536 MiB 硬门槛约 3.81 GiB；容量阻塞已解除。
- event 956 的自然 result/public/correction 验收仍占用赛事窗口。Beat 不能停止；不得 acquire shared lock、
  不得新增生产 TRA 联网或 DB 写、不得消费旧 `race_live=7543`。
- 当前运行态 `740a…cff2` 是 reference registry；此前 `3bac…a6da` 是 TRA canonical。二者不得混用、自动迁移
  或据此复用旧 proof。
- 只有 rollout owner 明确确认 event 956 正式公开和至少一个 correction 周期完成、lock absent、赛事链可安全
  暂停并给出当前 registry 身份后，才可为 UK ordinal 3 或任何后续样本采集 fresh 双主机 evidence/proof。

### 当前权威本地 target/source 状态

- 当前 target root：`/Users/mentianlu/.codex/umanews-target-reviewed-complete-20260829.9WzJJH`；
  ledger/manifest SHA-256 为
  `de5aabfb70257ba65d407cbf05f431595180ef475d0efd768438dca7b17b4264` /
  `a130d11a59d4324e92e8d3d02185aa48633b330e0561ce020d8b2d893956903f`。
- 12,048 条 reviewed COMPLETE target：GB 3,194、IRE 1,957、FR 1,891、USA 5,006；获批 R1 的
  9 项当前范围冲突已关闭，17 项范围外冲突继续保留审计记录。
- 当前 partition 已按 `2026-08-31` 日期老化刷新为
  `12,048 total / 11,939 due / 10,795 bulk-2005+ / 1,144 pre-2005 / 109 not_due`。bulk range plan
  仍为 32 个 `PROPOSED_NOT_APPROVED` batches，不能直接执行。
- 最新 current completion audit v4 root 为
  `/Users/mentianlu/.codex/umanews-graded-horse-current-completion-audit-v4-asof-20260831`，report SHA
  `3342772dd4a723ecc5cc4a6a52d02988bb952d75d0915cd9f0f1f62fdda5d13e`，marker 为
  `AUDITED_INCOMPLETE`。它以当前工具重新证明 12,048 target scope violation=0，但 11,589 due targets 仍缺
  current held result、approved provider IDs=0；不得视为全量完成。
- pre-2005 唯一当前 readiness root 为
  `/Users/mentianlu/.codex/umanews-pre-2005-anchor-readiness-complete-v12-20260831.YjcYhO/artifact`：
  `1,144 = 1,128 anchors + 16 calendar corrections + 0 unresolved`。1,128 anchors 中 477 条有精确日期、
  651 条仅有 edition year。
- 默认批准已发布 seed COMPLETE root
  `/Users/mentianlu/.codex/umanews-pre-2005-targeted-seed-approved-v2-20260831`（manifest `acb97c16…b951`）与
  correction APPROVED root `/Users/mentianlu/.codex/umanews-pre-2005-calendar-correction-approved-v1-20260831`
  （manifest `f7103943…07fdf`）；前者 network execution=false，后者 database apply=false。
- pre-2005 targeted plan 为 65 batches / 18,048 GET，ordinal 1 France 2000（20 seeds/320 GET）G3
  `78ea5faf…bae0` 已批准。旧 bulk ordinal 1 France 2005–2007 G3 `52b8b086…46f0` 绑定日期刷新前的旧 plan，
  现仅作历史证据、不得执行；新 plan ordinal 1 proposal/approval 为 `ac2235ae…4402 / 4473b116…bee9`。仍未
  proof/claim/network；窗口恢复后须以当前 exact scope 取得 fresh proof，且只可择一账号 scope。
- bulk runner 已逐页保存 exact response receipt/checkpoint；safe-stop 的显式 resume 复核原 approval、同一
  plan/OpenAPI/output/account、全部 cache 与 prior request count，使用剩余 ceiling 从下一 skip 继续。execution
  ledger 最终保留所有 attempts，任何 member/count 漂移都在网络前失败关闭。
- 当前机器可读 source coverage root：
  `/Users/mentianlu/.codex/umanews-source-coverage-not-due-aware-v5-asof-20260831`；manifest SHA-256
  `9f7378d932fa7ce2e2ef929c9917ad1043745fd3a57d0dd2c521cafef464ce55`。
- 12,048/12,048 target 均有来源状态，但这不等于已取得赛果：350 个 current-held；3,726 个 TOBA
  target 待独立审核；109 个官方 future target 为 not_due；183 个 past calendar target 仍需结果；7,680
  个目前只有来源路由。现有 reviewed held 多来源合并后是 350 条唯一 occurrence，另有 34 条第三方
  corroboration，不创建第二场赛事。
- 11 个英国候选已经形成独立 `PROPOSED_NOT_APPROVED` alias 包：
  `/Users/mentianlu/.codex/umanews-legacy-alias-proposal-v2-20260829.b8kgKj`，manifest/proposal SHA-256 为
  `3081e7cb5a8e50874a53ed1882e4379251e692b871dd6b7a4b794316530b25de` /
  `a49cab78fe23a164e83f22489fa4745818188ae544e9f80a38c2cd7751ca9423`，并绑定 generator SHA
  `b706bf025bdef074a65b973f088d38aa20e39773591652158caf4ff624578abd`。它只建议 3 组 series migration，
  覆盖 11 场/111 个 actual-starter slots；尚未由独立审核人批准，不能计入 held 或生成 seed。
- source coverage artifact 状态为 `review_required / PREPARED`、`execution_ready=false`。BHA、France
  Galop、Equibase 的公开条款不允许无许可的商业系统化抓取/复用；HRI、TOBA 未找到足以支持该用途的
  公开许可。因此非 TRA 来源默认只作 frozen human-reviewed reference，除非取得书面许可。TRA 条款允许
  application/website/data analysis、禁止直接转售；账号实际 credential/response entitlement 仍需 proof。
- France Galop 2026 当前确认 71 场、566 个 actual-starter slots、411 个去重名称 seed；71 个 winner
  proposal 因 target PREPARED 而 `runnable=false`。
- materialized 单马包现会保留字段矩阵和全部 response wrapper；已新增
  `racing-api-horse-p0-candidate.v1` 零写审核桥与
  `prepare_racing_api_horse_profile_candidate` 命令。每条履历必须回指冻结 results response，NR 不计
  starts，并列名次正确规范；manual lock、日港本地 crosswalk、逐场 authority 和模块审核仍是硬门禁。
- 生产 mapping 的名称集合与 snapshot 已纳入 `HorseNameVariant`，用于把受审本地名/官方欧字名/海外英文
  alias 召回同一 canonical profile；名称仍只做召回，不绕过 provider ID 或 DOB/sex/sire/dam 强证据。
- `HorseNameVariant.is_official` 已从强身份授权中解耦：双向 alias 还必须有完整 evidence URL/SHA，且
  authority host 与 reviewed local namespace（或一等 source + region）一致。proposal snapshot 同时绑定
  external linkage、有效期和 evidence URL/SHA；漂移后必须重建，不能沿用旧批准。
- production identity census 命令已实现为只读 artifact：all-staged 或显式 `hrs_*` scope 逐马冻结 provider
  ID、decision、current identity、official claim trust 与 profile snapshots；尚未在生产运行，不把本地测试
  artifact 当生产 inventory。
- 法国 Westover 与爱尔兰 Economics 已在本地隔离 staging 形成真实 P0 候选和显式双马 census；两份候选
  均为 `review_required/create_new_candidate`、字段无缺失/冲突、0 canonical 写。真实同名 search 的非目标
  results 只按同包披露 ID 排除，声明 parent 则绑定 payload SHA。详见
  `research/p0_real_candidate_and_identity_census_20260830.md`；这不批准 identity/module review 或 production apply。
- 两匹已形成 exact identity/module proposal `b9c2b6f7…a826 / e9ff2689…20a5`，均为
  `PROPOSED_NOT_APPROVED`。2026-08-30 的 `1496692 < 1572864 kB` fail-closed 是扩容前历史检查点；当前容量
  已通过，但 event 956 仍占用赛事窗口。本地 proposal 不得并入 shared registry，继续等待 rollout owner
  给出新的安全窗口与当前 registry 身份。
- Ireland model、TJCIS flat/jumps parser、Europe/Dublin 时区与 migration `0076` 已在本 worktree
  实现；下面的生产只读基线是实现前快照，不可用于否认当前本地能力，也不可冒充生产已部署。
- Ireland-specific IrishRacing 冻结结果页现可通过离线 adapter/package/admission；HRI 官方 HTML parser、
  全历史 coverage 与系统化复用许可仍是 gap。HRI 搜索结果可作人工发现线索，不能直接变成 held/runner。
- runner v2 已从五地区扩为六地区 recipe。Ireland recipe 保留 HRI official authority，但将其列入
  `blocked_sources`；唯一 `executable_sources` 是 IrishRacing，且 request policy 只允许其 HTTPS
  `/raceresults/` host/path。该代码状态不等于 Ireland 的 1,957 个 target 已具备可执行 URL。
- 外部冠军批量索引现有 fail-closed proposal/publisher。2024 Irish Champion 的 Economics 提案 manifest
  为 `694f6c0e…adca`，状态 `PREPARED_NOT_EXECUTABLE`；没有独立决定，不能进入 TRA 批次。
- reviewed-held actual-starter census root 为
  `/Users/mentianlu/.codex/umanews-held-actual-starter-census-v1-20260830.q8BroW/artifact`，manifest/census/
  summary SHA 为 `32b12aa7…32333 / 5916ed26…c056 / 262cc038…eb9`。350 场得到 3,192 个实际出赛槽位并
  排除 94 个 withdrawn/NP；`provider_horse_id` 全部为空，不能直接执行 profile batch。

## 最新生产只读基线

- 生产 Git HEAD：bef0cdc5034bd2516df9876b2a7dde2357f03495
- HorseProfile：52,372
- 旧正式历史目标中，英国/法国/美国符合本 change 年份/等级范围：
  - target：10,063
  - UK：3,169
  - France：1,890
  - USA：5,004
  - imported：4,673
  - pending：4,856
  - source_unavailable：521
  - ready：8
  - identity_review_required：5
- 当前 RaceEvent 相同筛选（包含非历史入口）：
  - events：5,467
  - events with results：5,153
  - events without results：314
  - results：41,122
  - UK：1,751 events / 14,652 results / 6,469 unique raw names
  - France：827 / 4,879 / 2,292
  - USA：2,889 / 21,591 / 7,192
- 已由这些赛果形成：
  - P0 source：15,814
  - unique P0 profile：10,279
  - completeness：10,279 empty；其余完整度均为 0

以上是实现前生产只读基线，不包含 Ireland；当前本地 model/parser 已支持 Ireland，但代码尚未发布，
生产也未重建四地区分母。当前计划以本节 12,048 行 reviewed COMPLETE target 为准，生产基线仅用于写前差分。

## 可复用能力

1. runtime/tools/prepare_tjcis_ics_catalog.py：1998–2026 TJCIS 全年目录、页上下文、declared count、
   source conflict 和 cache 审核。
2. runtime/research/collect_graded_race_participants.py：单年实际参赛语义、checkpoint、artifact、
   名称/状态审计。
3. runtime/research/collect_official_graded_race_results.py：官方结果 package 与 bounded runner。
4. P0 participant batch/release：候选 census、分批执行账本、完成资料桥。
5. p0_horse_production_apply.py：reviewed artifact、release manifest、dry-run、commit、receipt。
6. HorseRaceRecord shared upsert：canonical race key、旧记录接管和重复阻断。

## 已确认 TRA 契约

- /v1/horses/search：Standard，5 req/s。
- /v1/horses/{horse_id}/pro：Pro，5 req/s；DOB/sex/colour/breeder。
- /v1/horses/{horse_id}/results：Pro，5 req/s，文档为 full historical results，
  limit<=100、skip<=20000；没有 bulk 12 个月说明。
- /v1/results：Standard/Pro，5 req/s；默认最近 12 个月；历史 add-on 放宽到 2005-01-01，
  单次范围最多 365 天，官方建议逐日导出。
- 官方覆盖页当前 core：GB 209,193、IRE 55,430、FR 41,550、USA core 16,854；
  USA 全量依赖 North America add-on，账号实际 entitlement 必须 proof。
- 默认账号限速公开为 5 req/s；月度/并发总额未公开。
- TRA 允许用于应用/网站/数据分析，禁止未经许可直接转售；TRA 不是官方数据商。
- 外部冠军锚点只在第一阶段使用 search。目标 race 的全体实际出赛 `hrs_*` 跨赛事去重后进入第二阶段，
  直接读取 profile/results/parent；单匹保守上限为 `results_pages + 2 + 2*parent_count`。

## 阶段门禁

### Gate A：本地规格与测试

- 规格/设计/测试/任务/rollout 工件齐全；
- 工程审查无未关闭 P0/P1/P2；
- Ireland parser 和 schema 先有 RED；
- TRA 所有真实响应使用离线 fixture 验证；
- official crosswalk 的布尔标记、authority horse-record ID/namespace、冲突 claim 与 evidence snapshot 漂移，
  以及 read-only production census 重放/失败关闭均有 RED/绿色回归；
- 不需要生产/付费权限。

### Gate B1：Montjeu 单马网络 proof（G3）

精确包必须包含：

- host：api.theracingapi.com；
- paths：horse search/pro/standard/results；明确排除 `/v1/results`；
- scope：仅 Montjeu 与 1999 Arc occurrence；
- request ceiling：最多 16 次 GET，不设 retry reserve；
- min interval：250ms，全 run 共享；
- timeout/output/cache path/retention；
- database_writes=0；
- 日志脱敏与 safe-stop 条件。
- 使用 `exclusive_file` account state，并以限时 preflight artifact 证明所有其他 TRA caller 已关闭。

### Gate B2：四地区 entitlement/sample proof（独立 G3）

- paths：在 B1 基础上增加 `/v1/results`；
- scope：每地区至少 2 场/10 匹，含 IRE、同名、跨语言和多页 career；
- 分别列明 bulk historical、North America add-on 和 Pro entitlement；
- request ceiling 从冻结 sample plan 计算，最多 10% retry reserve；
- 使用 `shared_db` account limiter，或新的限时 exclusive proof；
- database_writes 只允许明确列出的 host-budget control row；业务表写入为 0。

### Gate C：代码发布（G2）

提供：

- exact commit/tree/image SHA；
- migrations 和 choices/data migration 区分；
- 测试与审查证据；
- 配置项全部默认关闭；
- 部署、health、rollback 命令；
- 不包含全量网络或生产数据 apply，除非逐项写入同一包。

Montjeu N1 前允许单独形成 proof-only Gate C 子包。当前候选绑定
`research/g2_proof_only_release_proposal_20260830.json`，只含 host collector、Django proof
service/command 和两项测试；零 migration、零 setting/flag 变化、零 TRA 请求、零数据库写入。该子包发布
不批准 foundation migration、N1 之外的网络、staging/canonical apply 或发布。candidate commit/tree/image
仍须在用户精确 G2 后生成并回填，不能把 `PROPOSED_NOT_APPROVED` 当发布许可。

### Gate D：全量网络导出（G3）

每批提供：

- target ledger/plan SHA；
- region/year/race/horse IDs 数量；
- endpoint 分类和 request ceiling；
- 估算运行时间、输出目录、resume checkpoint；
- source entitlement 与预算余量；
- database_writes=0；
- 上一批 summary/verifier。

### Gate E：生产 apply（G3）

每批提供：

- reviewed artifact/release manifest SHA；
- create/update/noop/record/identity 预计数；
- ambiguous/unreviewed/blocker=0；
- backup path/size/SHA/pg_restore list；
- maintenance/preflight/command；
- verifier 和 reverse/restore 回滚；
- 新 profile 不公开。

当前 production apply maintenance 合同默认要求 `P0_HORSE_PRODUCTION_PREFLIGHT_REQUIRED=true`：外层协调器
持有原 deployment-lock token 并停 Beat，内层 wrapper 只验证、不 acquire/release；artifact/package/release、
revision/image/database/migration、`apply_plan_id/source_batch_id/region/ordinal` 与 host evidence 必须精确绑定。
普通 web/worker 各一且健康/idle，赛事专用 worker absent，十个赛事同步开关与 race-live 调度开关全 false，
`celery/race_sync_v2=0`，`race_live` 只观测且前后不变。任一输入路径中间 symlink 也阻断。

exact reverse 由 `P0_HORSE_PRODUCTION_REVERSE_ENABLED=false` 默认关闭；即使临时启用，也只接受完整 receipt
identity/state SHA、active superuser 和显式确认。after-state 漂移或未捕获关联存在时不得部分反向，改走写前 dump。

## 运行次序

1. Ireland parser/model。
2. 四地区 target ledger。
3. TRA offline client/normalizer。
4. Montjeu 单马 proof。
5. 四地区 entitlement/sample proof。
6. 按冻结 88-batch 单日 range plan 对 10,795 个 2005+ target 逐批取得 fresh proof/exact G3 后运行 bulk_results。
7. 独立审核并发布 1,128 条 pre-2005 v2 seed；16 条 correction 走独立 correction-only approval，绝不进入
   TRA request plan；随后只对获批 seed 和 bulk gap 逐批运行 targeted_horse。
8. 每个 COMPLETE bulk run 生成 provider-native actual-starter stable-ID ledger；每个完整 targeted
   materialization 继续生成对应 ledger。read-only frontier 必须证明 execution receipt 与 stable ledger 1:1，
   targeted 路线还须证明 receipt→full materialization→stable 两段 1:1；验证 SHA、member set、去重、NR/unknown
   和 target occurrence 守恒。bulk 未达 frozen-plan 全部 88 批、pre-2005 targeted 未达 65/65 或任一 active 非空不得进入最终 merge。
9. 合并全部 bulk/targeted stable ledgers，按 provider `hrs_*` 全局去重；以 provider-native bulk/targeted components 生成
   exact occurrence coverage；pre-2005 targeted 必须逐 materialization 使用 provider-native targeted component，
   不得伪装成 held/external approval。确认 overlap/gap=0 后才规划全部唯一 `hrs_*` 的 Pro/parent/career。禁止再次 search、
   单批绕过 merge 或递归扩展 career 同场马。
   最终 source list 必须由 32-bulk + 65-pre-2005-targeted 组合 frontier 生成；13 马 France/Ireland pilot
   stable/held/external occurrences 已被 bulk 覆盖，不得作为第 98 个及后续来源混入。
   merge 后先运行 global coverage frontier，证明 v2 manifest source set 精确等于 97 个 frontier inputs，再执行其
   88 bulk-run + 65 targeted-materialization coverage argv；不得手工拼 coverage components。
10. identity mapping 和 module review。
11. 小批 dry-run/apply/verifier。
12. 按 ledger 继续，直到所有 target/horse 有可解释终态。

第 7 步的每批外部 anchor 必须先生成不可执行 proposal，由独立 reviewer 审核 exact target/page/winner/
output SHA，再发布 COMPLETE seed ledger。旧 exact-date 路线继续使用 v1；pre-2005 date-optional 路线使用
`proposed-targeted-horse-seed.v2 -> targeted-horse-seed.v2 / COMPLETE`，缺日期时仍必须以 edition year、
赛事名/alias、马场/alias、等级、discipline 和冠军名次唯一匹配。COMPLETE seed 只解除事实输入门禁；后续
batch plan、exclusive-account proof 与 TRA GET 仍分别取得 G3。来源页面抓取范围不得因某个单页 reference
扩大。

16 条 pre-2005 not-held/cancelled target 使用独立 calendar correction proposal/publisher。correction approval
scope 固定为 `CALENDAR_CORRECTION_PUBLICATION_ONLY_NO_DATABASE_WRITE`，不得生成 seed、不得进入 request
ceiling，也不得直接修改历史赛事数据库。10 条英国行没有 row-level URL/page SHA，必须通过其上游
source proposal manifest + candidate-row SHA 重放冻结 cache/分类；其余存在 row-level 证据的行继续绑定精确
URL/page SHA。运行前必须重验守恒式
`1,128 seeds + 16 corrections + 0 unresolved = 1,144 pre-2005 targets`。

reviewed held 扩展当前将 350 个 target 固定为 311 条既有 COMPLETE seed 复用 + 37 条 France Galop official
新增 winner candidate + 2 条官方 winner 替换 candidate。旧 proposal `d810272f…2441` 已被当前生成器重放
拒绝；新 proposal manifest `f950593c…f787` 仍为 PREPARED。只有独立 exact-SHA decision 才能发布
350 条 COMPLETE seed。获批后的保守投影是 26 批、5,600 GET 上限、单并发、≤4 req/s、批间 30 分钟；
投影不是 batch approval，每批仍需 fresh proof 与 exact G3。

350 场的 participant 分母另由 actual-starter census 固定为 3,192 个 occurrence slots。targeted-horse 每恢复
一场，必须把该场 TRA runner 集合与 census 逐行守恒，对 withdrawn/unknown 分别排除/阻断，并将 `hrs_*`
回填到 slot。只有全部 slot 均取得唯一 provider ID 后，才允许按 `hrs_*` 跨 target 去重并计算第二阶段 profile/
parent/full-career 的真实请求上限。

`prepare_held_census_tra_reconciliation.py` 已实现上述 PREPARED 对账层，真实输入前已验证 census 3,192 行、
350 target 与 held seed proposal 350 bindings 守恒。它还强制要求未来独立批准后的 COMPLETE 350-seed
artifact；只给 PREPARED proposal 会拒绝。当前既没有该 approved seed artifact，也没有真实 stable-runner
ledger，因此不得生成或声称任何 `hrs_*` binding；未来输出即使零 gap 也只是 requires-review candidate，
需独立 identity approval。

## Safe-stop

以下任一出现立即停止新请求或下一批：

- 401/403、账号 entitlement 不符；
- 429 未按 Retry-After 收敛；
- OpenAPI/schema fingerprint 漂移；
- pagination stalled/total drift/race_id payload conflict；
- target ledger/source policy/tool SHA 漂移；
- cache/manifest/COMPLETE 身份错误；
- identity 强字段冲突增加超过批次阈值；
- active production import/claim/lock；
- backup 未完成或 verifier 非零。

safe-stop 不是失败清零。保留已验证 cache、request ledger 和 completed receipt，修复后从精确
checkpoint 继续。

TOBA occurrence rollout 另要求 source physical rows、唯一 occurrence identities、flat targets 和
source-reused identities 四项守恒。审核提案中的候选排名不可执行；只有独立 hash-bound approval 才能改变
coverage。TOBA 只覆盖美国平地历史，美国 jumps target 必须继续留在其他 authority/TRA gap ledger 中。

official calendar rollout 必须按 target artifact 的同一 `as_of_date` 区分 `not_due` 与
`past_schedule_needs_result`。`not_due` 可进入 non-held target ledger，但不得生成 runners；past schedule
只有在正式 held/cancelled/postponed evidence 到齐后才能改变终态。当前适用范围仅为受审 2026 BHA /
France Galop，不能外推 HRI 或历史年份。

reviewed held 输入进入 occurrence compiler 前必须按 `target_key + local_date` 合并多来源引用。唯一较高
authority 行作为主 occurrence，较低 authority 行保存为 corroboration；同级最高 authority 冲突立即停止。
当前局部 ledger 只有 `350 held + 113 not_due + 11,585 unaccounted`，marker 为 `PREPARED`，不得作为
全地区完成、runner seed、网络许可或 production apply 输入。

compiler 命令只允许 `--occurrence-proposal-root` 和 `--non-held-proposal-root`；裸 JSONL 参数已删除。
target 全 accounted 仍不等于可执行，所有输入 manifest 必须同时为 reviewed/approved 且
`execution_ready=true` 才能生成 `COMPLETE`。

input approval publisher 不接受命令行口头 acknowledgement；必须读取独立 reviewer 的 regular decision
file，并由 exact decision SHA 和 proposal/output SHA 共同绑定。held consolidation 与 not_due subset 分开
批准，不能用一个决定扩大到 TOBA、HRI、past schedule、TRA 或 production。

网络入口的 OpenAPI 门禁固定使用
`research/tra_openapi_fingerprint_20260829.json`，文件 SHA-256 为
`c1dad02e0e53a48e6e7d889af2ce97032c79d0fbf56fe002ac67c6589a3a8b92`。命令必须同时传文件路径与该 SHA；
manifest 记录文件绝对路径、SHA、size、full/selected contract/schema 身份。该门禁不会请求
`/openapi.json`。若要在线刷新，先停止 N1/当前批次，生成新 G3，再以新响应重做独立 review 和冻结。

## 回滚

- network/artifact：停止 runner，保留或隔离不完整目录，不触及数据库。
- code：关闭新 flags，回滚到部署前 image/commit；choices migration 可保留。
- Ireland reclassification：使用 reviewed before/after reverse artifact。
- profile/career batch：优先 exact reverse ledger；无法证明精确反向时恢复写前 dump。
- 回滚后重新运行 target/identity/profile verifier 和关键公开页只读抽检。

## Stable-ID 第二阶段 rollout 门禁（2026-08-30）

1. winner-anchor 批次先恢复完整 target race/runner，形成 COMPLETE stable-runner ledger；不得以 horse name
   或 `provider_horse_id=0` 的 census 直接规划 profile。
2. 运行 census-to-TRA proposal；只允许 zero-gap 输出进入独立 review。publisher 必须重放 bound inputs 和
   output SHA，发布 COMPLETE bindings 后才进入下一步。
3. 运行 stable-ID batch planner。每批最多 5 个唯一 `hrs_*`，默认 207 GET/马；所有输出继续为
   `PROPOSED_NOT_APPROVED`，当前真实 seeds/批数/总 ceiling 未知。
4. 每批 fresh exclusive proof + exact G3；G3 endpoint scope 必须不含 `horse_search`，只允许 results/profile。
   ≤4 req/s、单并发、批间 30 分钟，页上限或 drift 触发 safe-stop。
5. 网络 COMPLETE 之后仍需 identity/module review、写前备份、dry-run、apply approval 和 verifier；不得从
   profile artifact 直接跳到生产 HorseProfile。

### 2026-08-31 mixed-source partial rollout 更新

1. stable ledger 只引用 held 集合的部分 target 时，可用 `--stable-scope-only` 生成 scoped proposal；所选 target
   仍须 source/TRA count 和逐马 binding 全守恒。该模式不批准未选 target，也不接受 approved held map 外的 seed。
2. France scoped held COMPLETE 与 Ireland external single-race COMPLETE 通过 planning-only coverage 合并；
   occurrence key 并集必须 13/13、overlap=0、gap=0。coverage 的 network/database authority 固定 false。
3. 当前 coverage manifest SHA 为
   `a3e8963ba923d5f227b70903341a4f58bef148279781726abbe3416621f5c964`；零 search plan manifest SHA 为
   `51eccdcca26edc3d7aebd7cf8b945953f6895cc11052e0694e4e7a236a4fc230`，3 批/13 马/2,691 GET ceiling。
4. France ordinal 1 G3 approval SHA 为
   `1228acefb4a10df031cb5575db7dad2f826e82fb60bc4f8b78a43102a25aa2d6`，scope 只含 results/profile/fallback，
   不含 search。execution ledger 仍 `active=null / completed=0`。
5. event 956 owner 未明确让出窗口前，不生成 fresh proof、不 claim、不发出请求。恢复后本批与 pre-2005/bulk
   首批三种账号 scope 只能择一串行执行。
6. fresh proof 前先运行 `preflight`。它必须返回 `ready_for_fresh_exclusive_proof`、network/DB=0、
   proof_loaded=false、ledger_mutated=false；同时确认 execution ledger 与 lock SHA 前后不变、output/budget
   目录 absent。preflight 不能替代放行或 proof，放行后应以现场 bytes 再运行一次。
7. bulk range 使用同一原则：preflight 必须逐字匹配下一 ordinal 的 plan/G3/output/budget/account/OpenAPI，返回
   target count、date ranges、request ceiling 与唯一 endpoint `bulk_results`。当前 France 2005–2007 基线为
   105 targets / 3 ranges / 603 GET；ledger/lock SHA 前后不变。
8. pre-2005 France 2000 的 targeted preflight 基线为 20 anchors / 320 GET，endpoint 含 horse search；不得
   误用 stable-ID France 2023 的 zero-search 参数。三种候选首批均 ready 时仍只允许选择一个账号 scope。
9. 首个 live scope 已由 selection SHA `31d3b6ee…836b` 固定为 stable-ID France 2023。event 956 放行后只为
   该 scope 重跑 preflight/proof/claim；pre-2005 与 bulk alternatives 不得并行生成 proof。
10. v1 selection 已由包含全部执行路径/参数的 v2 `366dde54…e0a6` 取代。现场只运行
    `audit_selected_first_live_scope.py --selection-root ...v2... --selection-sha256 366dde54...e0a6`；必须返回
    `ready_for_event_release_and_fresh_proof` 后才能采集 proof。v1 仅留历史，不再作为执行入口。
11. selected batch COMPLETE 后先全量 materialize，再运行 `prepare_selected_batch_postprocess_plan.py`。只有 ledger
    最新 completion 正是 selected batch、`active=null`、5/5 seed 与唯一 `hrs_*`/run manifest 全部守恒时才生成
    `PREPARED_NOT_AUTHORIZED`；staging apply、module publish、canonical apply 仍分别等待后续授权。
12. staging 正常入口固定为 `stage_racing_api_targeted_batch`：同一 materialization 先全批 dry-run，再在一个外层
    事务中 apply；任一后段 run 失败整批回滚。逐马 apply 只保留恢复审计用途，不能替代 batch report。
13. staging 后用 `prepare_racing_api_horse_profile_candidate_batch` 生成 exact candidate batch。只有
    `PREPARED_REVIEW_REQUIRED / blocked=0` 才把其 manifest SHA 分别传给 identity/module `prepare-batch`；blocked、
    重复 `hrs_*` 或 batch+individual 参数混用不得删行后继续。
14. identity/module proposal 生成后，以 candidate-batch root + manifest SHA 运行 current completion audit；不要
    同时传逐文件 candidate 参数。`AUDITED_INCOMPLETE` 只证明当前输入守恒，最终完成仍等待 reviewed research、
    production receipts/inventory 与 public verifier。
15. 全部 production apply 完成后，在只读数据库窗口运行
    `generate_racing_api_global_completion_inventory --stable-ledger-root <merged-v2> --stable-ledger-manifest-sha256 <sha> --output-dir <new-dir>`。
    该命令不联网、不写库；只有 `canonical_database_complete=true` 才可把其 public-page targets 交给独立 verifier。
16. 先用 `manage_racing_api_global_public_page_verification --prepare-plan` 回绑 inventory manifest SHA 与每行
    `hrs_* + profile_id + public_path`，冻结每匹马的所有履历页与 exact record order；本步 network/DB=0。
17. 只有赛事 owner 另行释放公开页联网窗口后，才以
    `RACING_API_PUBLIC_VERIFY_NETWORK_ENABLED=true` + `--allow-network` 双门禁执行同一命令的 `--execute`；请求间隔
    不低于 0.5 秒、禁止 redirect/proxy/netrc/credentials、单页上限 5 MiB。保存每页 response body/SHA、HTTP/final URL
    与内容 blocker。单次 execute 最多 50 个连续 ordinal；全部 chunks 后再用 `--merge-chunks` 零联网重验 exact
    1..request_count coverage。HTTP 200、抽样页面、inventory `COMPLETE_READ_ONLY`、单个 chunk 或 verifier 自身
    任一单项都不能生成最终完成结论。
18. 每个 proposal child 或 approval child 变化后先运行 approval readiness；已验证 proposal prefix 可在后续批次等待时
    开始人工 identity/module review，但 publisher argv 只有 reviewer 完成 exact decisions/四模块核对后才可执行，禁止
    自动批准。全量 identity/module approval 完成后、identity apply 前，再以 complete/inactive global enrichment ledger 与六类
    exact postprocess parents 运行 `prepare_racing_api_global_review_batch_bindings.py`；必须得到 automatic wrapper
    `COMPLETE`，禁止手工逐行拼 JSONL。再以 exact merged stable ledger、wrapper root+manifest SHA 运行
    `prepare_racing_api_global_review_aggregate`；aggregate 仍须独立重放 candidate、identity proposal/approval、module
    proposal/approval，并覆盖 stable `hrs_*` 全集且批间无重复。
19. production inventory 与 merged public verification 均 complete 后，运行 `audit_racing_api_global_completion`，
    传入 review aggregate、inventory、public verification 三个 root+manifest SHA。只有 stdout 和 marker 同时为
    `AUDITED_COMPLETE / completion_achieved=true` 才可声明完成；任一 safe-stop 必须回到对应批次修复，不删分母。
