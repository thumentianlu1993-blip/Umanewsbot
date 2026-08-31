# 工程审查记录

审查日期：2026-08-29

审查模式：Full。依据 plan-eng-review 的架构、数据流、迁移、任务行为、测试、性能、部署与文档
一致性维度，对本仓库当前 docs/changes 原生变更包做两轮自审。根 AGENTS.md 已明确禁止旧
OpenSpec 工作流，因此本审查不创建或更新旧状态文件。

## 审查范围

- spec.md
- design.md
- test_cases.md
- tasks.md
- rollout.md
- 当前 HorseProfile/HorseRaceRecord/External*/Historical*/P0 模型与服务
- 生产只读 target/event/result/profile baseline
- TRA 最新 OpenAPI、覆盖、套餐和条款

## 第一轮 findings

### ER-01 P1：爱尔兰在当前模型和 parser 中实际缺失

证据：RacingRegion 没有 Ireland；TJCIS parser 将 IRELAND/IRISH JUMPS 放在 unsupported section，
测试明确期望 Irish race 被跳过。若直接复用英国范围，会遗漏爱尔兰并伪造四地区覆盖。

修正：新增 Ireland choice、Europe/Dublin、IRE provider mapping、flat/jumps parser 和独立
declared-count 分母；旧数据只走 reviewed reclassification artifact。

状态：已关闭。

### ER-02 P1：TRA 返回不能作为应到分母

如果以 /results 返回反推目标，接口缺失会被误报为“没有赛事”，特别是 2000–2004、美国 add-on
和当前年度。

修正：TJCIS/地区目录 target ledger 独立冻结；target/race/participant/horse/profile/career 分层
统计。

状态：已关闭。

### ER-03 P1：External staging 不能代表赛事已经落表

初稿只强调 ExternalRace staging 和 HorseProfile apply，未明确 4,856 pending 等正式历史 target
如何变成 RaceEvent/Result。这样单马履历可以存在，但赛事数据库仍不完整。

修正：TRA normalized bundle 必须转换为现有 historical reviewed candidate，经 calendar admission、
dry-run、receipt、verifier 后才推进 production_race_resolved。

状态：已关闭。

### ER-04 P1：4 req/s 与 race-live 并发会突破账号级 5 req/s

单独给 backfill 限流仍可能和现有 TRA race-live caller 叠加。

修正：要求账号级共享 limiter；共享实现前，preflight 必须证明 race-live scheduler/runner 与其他
TRA claim 全部关闭。G3 包必须包含该证据。

状态：已关闭。

### ER-05 P1：单马 results 会导致整场 raw payload N 倍复制

每个目标马的 results 包含全体 runners；若直接写 ExternalHorseHistory.raw_payload，会形成明显
存储膨胀并增加 hash/replay 漂移面。

修正：整场 raw page 进入内容寻址共享 cache；HorseHistory 只保存目标行、race_id、cache SHA。
定义 raw 90 天保留和长期 provenance。

状态：已关闭。

### ER-06 P1：把 provider_gap 当 change 终态会提前宣称完成

用户要求持续到全部落表。运行批次允许 gap 以安全停止，但整个目标不能因此完成。

修正：区分 run terminal state 与 goal completion；所有已举行目标最终 unresolved gap 必须为零，
否则继续替代来源或人工 resolution。

状态：已关闭。

### ER-07 P1：bulk /results 无法覆盖 2000–2004

OpenAPI 的 historical add-on 最早到 2005-01-01。只设计 bulk 会永久遗漏前五年。

修正：targeted_horse 读取外部唯一 runner/winner anchor，通过 full horse results 恢复整场 runners；
Montjeu 1999 作为该链首个 proof。

状态：已关闭，真实历史非空率仍待 G3 proof。

### ER-08 P2：provider complete 与官方完整生涯混淆

TRA 条款明确不是官方数据商；分页 total 对齐只能证明 provider response complete。

修正：拆分 provider_profile/page_profile/provider_career/authority_career/local_identity 五类状态；
现有 career authority 字段只在独立证据下升级。

状态：已关闭。

### ER-09 P2：爱尔兰 choices migration 不应携带模糊数据迁移

按马场名或赛事名批量 UPDATE 会误改英国/跨国记录，且难以回滚。

修正：schema migration 与 reviewed data reclassification 分离，后者有 prepare/dry-run/apply/
verifier/reverse artifact。

状态：已关闭。

### ER-10 P2：长任务的事务与恢复边界不充分

全量请求和数万 profile 不能成为单 task/单事务；worker 退出会造成重复或长锁。

修正：target 250、horse 100、parent 250、apply 100 的默认分片；短 claim、fencing、连续 ordinal、
completed receipt 和逐批 verifier。

状态：已关闭。

## 第二轮一致性复核

### 架构与数据流

- target ledger、source cache、provider staging、identity、P0 candidate、正式 apply 边界清晰。
- network export database_writes=0；apply 不联网。
- 缺失正式赛事已接回 historical admission/receipt，不再形成第二条无门禁写链。

结论：通过。

### 数据库与迁移

- Ireland/TRA choices 是 additive。
- 新 identity 唯一约束以 provider external ID 为主，不以 normalized name 全局唯一。
- name variant 重名允许存在，唯一性必须限定在绑定对象、source、kind 和 normalized value。
- reclassification 是独立 data action，不进入 schema migration。

结论：通过；具体 migration 编号和 PostgreSQL lock 行为在 RED/实现阶段再审。

### 任务、失败与恢复

- 请求预算、429、分页停滞、schema drift、cache 身份、claim 和 receipt 均有 fail-closed 测试。
- run gap 不冒充 goal complete。
- 当前年度 future/not_due 与已举行 unresolved 分开。

结论：通过。

### 测试

- tasks 遵守先测试、再实现、再验证。
- SQLite 与 PostgreSQL 分层；并发、约束、事务和 rollback 不只依赖 SQLite。
- Montjeu 是真实 proof 目标，但未把未请求值写成已确认事实。

结论：通过。

### 性能

- 请求量由真实 H/P/A/R/S census 计算，不在未知前硬编码。
- 全局父母 ID 和 race payload 去重。
- 分片与可跨日 resume 适合数万马规模。

结论：通过；G3 前必须补真实账号月额和 entitlement。

### 发布与回滚

- G1/G2/G3、代码部署、全量网络、生产 apply 分离。
- 有 backup、maintenance、receipt、reverse ledger 与 dump restore 路径。
- 新 profile 默认 draft，无自动公开或外发。

结论：通过。

## Verdict

APPROVED_FOR_RED_TESTS

该 verdict 只批准进入本地测试先行的实现阶段，不构成 G2、付费网络 G3、生产部署或数据 apply
授权。完整实现后仍需只读独立代码审查和精确发布包。

## 2026-08-29 实现检查点复审

已验证的实现范围：Ireland choices/parser/timezone 与 `0076`；TRA source、ExternalHorse 扩展、
HorseExternalIdentity/HorseNameVariant 与 `0077`；targeted/bulk/batch artifact runner；HTTP allowlist、
脱敏认证、分页、race hash、actual starter、Pro fallback、parent profile；External staging
dry-run/apply receipt；只读 identity decision。聚焦测试 `112/112`，fresh SQLite migration 到 `0077`。

实现审查同时保留以下发布后续阻断，不得因本地测试全绿而降级：

- P1：30 个 TJCIS declared/parsed conflict 未关闭，目标总账只能是 `PREPARED`。
- P1：production target 与 TJCIS 的 series alias/date 尚未逐项对账，不能直接启动四地区 bulk。
- P1：历史 backfill 尚未接入生产 TRA 账号级共享 limiter；Montjeu proof 只能在证明独占调用窗口后执行。
- P1：当前 normalized career 与每 seed raw cache 仍有重复，跨 seed 的 race/parent content-addressed pool
  未完成，不适合直接扩大到数万马。
- P1：External staging 已可受控写入，但 canonical HorseProfile/RaceEvent reviewed bridge、identity 决策
  apply、reverse ledger 和生产 verifier 尚未完成；不得把 staging apply 当作最终落库。
- P2（部分关闭）：三个网络 CLI 与 artifact runner 已在首个请求前重验 SHA-bound 本地 selected
  fingerprint，live 响应也在下一请求前走 endpoint-specific schema/pagination 校验；真正在线读取
  `/openapi.json` 仍未执行，因为它不在 Montjeu N1 已批准 path/request scope 内，须另取 exact G3。
- P2：PostgreSQL 并发/rollback、受影响完整回归和独立只读代码审查尚未执行。

检查点 verdict：`G2_CANDIDATE_FOR_DISABLED_FOUNDATION_ONLY`。

该 verdict 只表示可以形成“全部网络/写入开关关闭”的代码发布候选；不批准 Montjeu paid proof、批量
网络、External staging 生产写入、canonical apply 或公开发布。上述 P1 在相应阶段前必须关闭。

## 2026-08-30 reviewed-held participant census 复审

- 发现旧 occurrence `actual_starter_names` 实际等于数字名次 result set，会漏 PU/F/UR/BD 等已起跑马；该集合
  继续用于 winner seed 没有问题，但不能作为 participant completeness。
- 修正后的离线 census 只消费 exact target/held/Wayback SHA 与冻结 cache：350 target -> 3,192 actual-starter
  slots，明确排除 94 withdrawals；unknown start status fail closed。
- source runner key 与 exact name 都不作为 canonical identity。3,192 行 `provider_horse_id` 全为空，同名跨场
  保留独立 occurrence row，避免跨语言/同名误合并。
- 全量第二目录重放逐字节一致，census 专项 `7/7`；加入批准链 reconciliation 后 research `365/365`。本复审只
  批准 PREPARED 离线分母，不批准 TRA 请求、stable-ID 自动绑定、profile batch、数据库写入或生产发布。

检查点 verdict：`APPROVED_FOR_PREPARED_ACTUAL_STARTER_CENSUS_ONLY`。

后续复核发现 stable-runner ledger 的内部 COMPLETE 尚未绑定外部 census 分母。已增加独立 PREPARED
reconciliation：350 seed-target mapping 守恒、独立批准 COMPLETE seed 全链、target 元数据与 start status
先验、同场名称仅作召回、count/name gap 显式输出，candidate 仍需独立审核。专项 `8/8`、research
`365/365`；真实 approved seed/stable-runner 输入未出现，本次不形成任何 provider binding。该补充不改变
上述只读 verdict。

## 2026-08-29 方案限定复审（实现继续前）

本节只记录方案复审，不替代实现后的独立代码 review。复审发现并要求在相应实现前关闭：

- P1：账号级 limiter 缺少共享状态、fencing、崩溃/时钟和 race-live 接入合同；已在 design/test/rollout
  中锁定 `shared_db` 与 `exclusive_file` 两种互斥模式。
- P1：TRA staging 到正式 RaceEvent/Result 只写了原则；代码核对进一步确认旧 import layer 无法覆盖
  2025 和 2026-07-16 之后，已要求新增 manifest-bound `graded_horse_backfill` layer，并复用同一
  admission/receipt/verifier。
- P1：identity resolver 之后缺 reviewed apply/reject/rebind/reverse 状态机；已在 design/test 中补齐。
- P2：per-seed 目录与跨 seed 内容寻址要求冲突；已锁定 batch-level object pool。
- P2：Montjeu 与四地区 entitlement proof 混为一个 G3；已拆成 B1/B2。

当前方案复审 verdict：`REVISE_UNTIL_CONTRACT_TESTS_GREEN`。这不是发布或网络授权；上述合同完成实现、
测试和独立代码 review 后再形成新的关闭态 G2 候选。

## 2026-08-29 合同返修复核

上一节的四个主要实现缺口已关闭：账号级 `exclusive_file` 预算具备并发、崩溃不退款和时钟回退测试；
新增 `graded_horse_backfill` layer 与 target snapshot/historical bridge；跨 seed 使用内容寻址 pool；
reviewed bind identity 已有 receipt、apply/replay/reverse/verifier。目标 parser 另修复三类确定缺陷，账本从
`12,039 / 30 conflicts / 13 scope blockers` 收敛到
`12,047 / 26 conflicts / 9 scope blockers`，仍正确保持 `PREPARED`。

后续审计发现 target builder 汇总逐年结果后未再次运行 parser 已有的全局同名 series 消歧。修复后
`--network none` 重建仍为 12,047 行；排除身份键和本机 cache path 后事实行零增删，仅 226 个
series/target key 规范化（英国 139、美国 87）。新版 ledger/manifest SHA 为
`f04a7d58…9481 / c3675dd1…bf19`，9 个 blocker payload SHA 不变；旧 audit 和提案全部重新绑定，状态仍
保持 `PREPARED`。

本次影响面验证为纯离线 `52/52`、TRA/identity/bridge/date 等 Django `162/162`、inventory/batch
相邻回归 `110/110`，合计 `324/324`；fresh SQLite migration 到 `0079`、Django check、migration drift、
compileall、diff check 均通过。完整 `stable` 检查未通过且被手工停止：已执行 `4,445` 项时为
`32 failures / 144 errors / 128 skipped`，未完成归因，不作为绿色证据。

仍未关闭的发布阻断：`9` 个范围内 source conflict；全部目标日期/冠军 anchor；online fingerprint
safe-stop；identity `create/reject/rebind` 与产品字段 release；PostgreSQL 并发/rollback；独立只读代码审查。
Montjeu 的真实 `hrs_*`、TRA career 总场次和 1999 Arc occurrence 仍需付费 G3 才能验证。

返修复核 verdict：`LOCAL_CONTRACTS_GREEN_REVIEW_PENDING`。它只确认上述本地合同已经转绿，不批准
commit/push/merge/deploy、付费调用、staging/canonical 写入或公开发布。

跨年份 series 修复、旧 bundle 重审、Finale 冻结缓存零网络重绑和差分审计器后的聚焦纯离线组合为
`59/59`；这
是原 `52/52` 之后的增量验证，不改写未通过的完整 stable 结论。

2026 英法官方赛历的后续审计把名称/场地/OCR/等级匹配器收紧为 fail closed。最终冻结结果为
`375 source = 373 candidate + 2 explained source gaps`、`497 targets = 373 candidate + 124 issues`；
已有结果证据 `48/48` 场、`314` 匹与官方日期一致。唯一精确赛名优先于 OCR 距离，显式等级为硬门禁，
冠名与场地只走逐项 alias；没有把 scheduled 日期当 held result。最终 manifest SHA 为
`6419b166…366b`，并绑定 audit/matcher SHA；仍为 PREPARED、零网络、零写库。新增 source-discovery
完整模块 `88/88`、本变更纯离线研究组合 `61/61`、官方赛历审计 `2/2` 已通过；只读 AST、Django
system check、migration drift 和 diff check 也通过。该审计不关闭 target COMPLETE、付费 proof
或生产 apply 门禁。

## 2026-08-29 AQPS/France Galop 公报与 stable-ID 二阶段增量复核

上一节 `f04a7d58…9481 / c3675dd1…bf19` 与 official audit `6419b166…366b` 已被 AQPS 语义修正取代，
只能保留为历史差分证据。当前 target ledger/manifest 为
`88313a59…61a49 / b507d21d…61ec5d`，事实行零增删、9 个范围 blocker 不变；当前 official audit
manifest 为 `2e78d352…071f`。

France Galop 官方公报 release/audit 已从 AQPS 子集扩大为 52 场 flat 与 19 场 obstacle G1/G2/G3、566 条
actual-starter rows、411 个去重马名，并生成 71 个冠军锚点提案。target 仍 PREPARED，因此提案
`runnable=false`；没有付费 TRA 或数据库写入。扩大解析修复了无括号/有括号负磅换行误识别、obstacle
discipline+grade 格式和 Prix du Bois 临时转场的 series-default/actual-occurrence 分层。当前 flat/
obstacle audit manifest 为 `e9fb1885…2e53f / 969b233d…5e9a9`。

“冠军锚点找回整场 runners 后如何补齐其他马”这一实现缺口已关闭为显式二阶段：从 materialized
target races 生成每个唯一 actual-starter `hrs_*` 一条的稳定 ID ledger；同一马跨多场保留全部 target
occurrence 但只补全一次；直接读取 profile/full results/parent，不调用 search；career 的其他同场马不
递归扩展。总账和 direct-ID 定向测试通过，原有 targeted/batch/materialization 测试继续通过。

增量 verdict：`LOCAL_TWO_PHASE_CONTRACT_GREEN_REVIEW_PENDING`。该 verdict 不批准 target conflict
签署、付费调用、commit/push/merge/deploy、External/canonical 写入或公开发布。

## 2026-08-29 来源覆盖、rollout 与追踪矩阵复审

按 `plan-eng-review` 重新审查当前实现后发现三项方案级问题：

1. P1：没有逐地区/年份、机器可读的来源覆盖与 fallback/条款状态，France 早期、Ireland 和 USA
   unmatched 无法从文档判断下一动作。
2. P1：rollout 仍写 Ireland model/parser 未实现，并沿用实现前 10,063 场生产快照，可能误导执行者。
3. P2：`test_cases.md` 的 E10/E11 重号，且 requirement、test、task、artifact 之间没有稳定追踪关系。

已完成修正：新增 `build_graded_race_source_coverage_plan.py` 及测试，生成 12,047 行逐 target 计划和 309
个 region/year/grade/discipline bucket；旧英法证据重审后 338 个 target 绑定 372 个 current-held
occurrence，legacy-rebind/orphan 均为 0。12,047 条均有来源路由，但大部分仍没有 held result，artifact
保持 `review_required / PREPARED / execution_ready=false`。rollout 已改用
当前 12,047 场四地区分母并把旧生产快照标为实现前基线；E12–E18 已重新编号，并新增
requirement -> test -> task -> evidence 矩阵。

本轮方案 findings verdict：`PLAN_REVIEW_FINDINGS_CLOSED_EXECUTION_NOT_READY`。这只关闭三项文档/可审计性
findings；9 个 target blocker、来源条款、TOBA/legacy review、TRA entitlement/credential、真实网络 proof、
identity review 与生产 apply 仍未关闭，因此不构成执行、发布或写库批准。

## 2026-08-30 proof-only G2 最小发布复审

凭据注入后现场确认 production 缺少 exclusive proof generator。Full review 的 Scope Challenge 拒绝为解除
N1 前置门禁而连带发布 Ireland/staging/identity 与 migration `0076–0079`，改为 latest
`origin/main@409f2ac6…121` 上的 5 文件 proof-only 候选。

Round 1 发现并关闭两个 P1：service 依赖 migration 0077 才存在的
`ExternalDataSource.THE_RACING_API`。改用稳定字符串 source key 后，候选可运行于旧 schema。随后确认
local credential/runner 与 production runtime 为双主机拓扑，单 host evidence 会漏掉另一端 one-shot；
已升级为 `runner + production` 两份 v2 evidence、不同 hostname 的硬门禁。修正后 host `2/2`、Django
`6/6`、check、migration drift、pycompile、两个 Compose config 与相邻 race-data/race-live/deployment
contract `123/123` 均通过；另补管理命令脱敏 stdout 测试。Round 2 重读候选、测试、rollout/runbook 和
failure modes，未发现新增 P0/P1/P2。

复审 verdict：`PROOF_ONLY_G2_CANDIDATE_REVIEWED_NOT_APPROVED`。它不授权 commit/push/merge/deploy，
不授权 Montjeu 之外的网络或任何数据库写入；精确范围见
`research/g2_proof_only_release_20260830.md` 与 proposal JSON。

## 2026-08-30 TOBA 双向 occurrence 分母复核

既有 coverage 只汇总 3,726 个 TOBA-bound flat targets 和 461 条原始 issue，没有保存全部 source/target
census，也没有显式说明 TOBA 不覆盖 US jumps。新增 proposal builder 后，3,941 physical rows、3,940
unique source identities、3,985 flat targets 和 184 jumps targets 均有唯一状态；已自动绑定 source/target
从 reviewer candidate pool 排除，8 个 reused source identities 与 259 个 target issues 分侧保存。

复核 verdict：`TOBA_REVIEW_PACKAGE_CONSERVED_NOT_APPROVED`。该 verdict 只确认审核包可审计、可重放；
`210 source + 259 target` 的决定仍需独立 approval，美国 jumps 仍是来源 gap，因此不能宣称美国 occurrence
或 actual-starter 分母完成，也不批准任何 TRA 请求或数据库写入。

## 2026-08-30 reviewed held 多来源合并与局部总账复核

现有 reviewed inputs 的 384 行中，34 组 France Galop official 与 ZEturf reviewed references 具有完全相同
的 target/date。新增 consolidation 层以 authority priority 唯一选择 official row，同时保存第三方
corroboration；同级最高 authority 冲突失败关闭，不同日期不折叠。输出为 350 held occurrences/targets。

与 113 条 reviewed `not_due` 装配后，12,048 target 全部分配为 350 held、113 not_due、11,585 explicit
unaccounted；地区 gap 仍为 GB 2,956、IRE 1,957、FR 1,666、USA 5,006。

复核 verdict：`PARTIAL_OCCURRENCE_LEDGER_CONSERVED_NOT_COMPLETE`。该 verdict 只证明现有 reviewed evidence
不会因多来源重复而制造赛事，且所有剩余 target 可见；它不关闭 TOBA、HRI、历史官方结果、actual starters、
TRA 或 production apply 门禁。

补充修正：原 compiler 虽记录裸 JSONL SHA，但没有证明文件来自哪个上游 proposal，也可能在输入尚未批准
时因 target 恰好全 accounted 而生成 COMPLETE。CLI 现只接受 proposal root，并验证 marker/manifest/
generator/target/output 身份；新增 `input_execution_ready` 和 `needs_input_approval` 终态。

修正后 verdict：`MANIFEST_BOUND_OCCURRENCE_COMPILE_FAILS_CLOSED`。occurrence 专项 `14/14`；加入
publisher 后相邻聚焦 `37/37`、完整 research `331/331`。

approval publisher 又将 readiness mutation 独立出来：只消费 regular decision file + exact SHA，强制
非实现者声明、带时区时间、immutable review reference 与全部 output SHA；复制原始 bytes 后才发布
APPROVED marker。程序不能证明真实组织身份，因此独立性仍需 owner/reviewer 治理，当前没有 approval。

publisher verdict：`APPROVAL_PATH_IMPLEMENTED_DECISIONS_PENDING`。

## 2026-08-30 Ireland 外部冠军锚点链复核

Ireland 1,957 个 target 仍全部位于 occurrence gap；HRI 页面搜索结果能证明官方结果产品包含赛事和 runner
字段，但直接自动化访问返回 403，且未找到可支撑商业系统化复用的公开许可。方案没有因此伪造 HRI parser，
只把既有 IrishRacing parser 扩展为 Ireland-specific 离线 provider，并保留第三方 authority 分类。

外部名字路径原先仅在四地区样本 builder 内读取一个 PREPARED Netkeiba reference，缺少可扩展的独立批准
合同。新增批量 anchor index、proposal builder 和 publisher 后，target/index/capture/request/source/result/
seed/evidence 全部 SHA 绑定；同一 capture 不可复用，publisher 重验事实守恒并拒绝实现者自批。测试中的
批准输出可被现有 batch planner 读取，但 batch plan 仍保持 `PROPOSED_NOT_APPROVED`。

复核 verdict：`EXTERNAL_WINNER_ANCHOR_PATH_FAILS_CLOSED_REVIEW_PENDING`。当前 Economics 一行提案已确定性
重放一致，但尚无独立决定；没有 TRA 请求、数据库写入或 HRI/Netkeiba 系统化抓取许可。

## 2026-08-30 Ireland runner v2 recipe 复核

runner v2 现包含六地区 exact recipe。Ireland 把 authority 与 execution 拆分为
`official_sources=[hri]`、`blocked_sources=[hri]`、`executable_sources=[irishracing]`；adapter discovery
只遍历 executable source。descriptor 与 adapter 双层校验 IrishRacing 的 HTTPS host 和
`/raceresults/` path，HRI provider、HRI URL、伪标 provider 或放宽 request policy 均在 cache 前拒绝。

复核 verdict：`IRELAND_RUNNER_ROUTE_FAILS_CLOSED_COVERAGE_MISSING`。相邻 runner/source 测试 `90/90`
（`1 skipped`）。新增 target-complete readiness 审计后，1,957 行全部为 HRI blocked、IrishRacing approved
direct URL missing，manifest/ledger SHA 为 `d6f71a65…205f / 0810e662…c27e`，空目录重放一致；完整 research
`342/342`、py_compile 与 diff check 通过。该结论只关闭离线执行边界，
不关闭 HRI parser/许可、IrishRacing URL coverage、Ireland 1,957 occurrence、TRA 或数据库门禁。

## 2026-08-30 reviewed-held winner seed extension 复核

350 个 held target 的 350 份 cache 已全部通过 path/size/SHA；278 份 ZEturf/Sporting Life cache 离线 parser
零失败，result name set 与现有 actual-starter set 全部一致；71 场 France Galop embedded starter count 全部
一致。提案逐 target 复用既有 313 条 COMPLETE seed，并只为剩余 37 个 organizer-official 唯一冠军生成
candidate。Bright Picture 两次获胜保留两条 occurrence seed，不按名称预合并。

复核 verdict：`HELD_WINNER_EXTENSION_CONSERVED_REVIEW_PENDING`。最终 manifest/output SHA 为
`d810272f…2441 / f18b6a1b…249b / 5f7d3783…705e / f4d568e8…24cd`，空目录重放一致；独立 publisher
输入重放、自批/无时区/漂移拒绝均有测试。专项 `8/8`、完整 research `350/350`。该 verdict 不批准 37 条
候选、350-seed COMPLETE、26 批/5,600 GET 投影、TRA 请求或数据库写入。

## 2026-08-30 zero-gap approval 与 stable-ID planner 补充复核

- reconciliation publisher 只接受 expected/TRA/binding 全量相等且 review/count/unmatched 全为 0；它重放
  census、seed proposal、独立批准 seed artifact、stable ledger 与三份输出，decision 自批、无时区、SHA
  漂移或非零 gap 均失败关闭。
- stable planner 同时绑定 stable manifest 与 approved reconciliation manifest/decision/horse-ID set；默认
  201 results pages + 2 profile + 4 parent profile = 207 GET/马，5 马/批，≤4 req/s、单并发、30 分钟间隔。
- execution ledger 的 endpoint scope 已按 `search_requests_per_seed=0` 排除 `horse_search`；旧计划兼容路径和
  非法参数均有回归覆盖。
- 专项 `10/10`、完整 `runtime/research 375/375` 通过；没有生成真实 approval、plan、G3、网络请求或 DB 写。

补充 verdict：`APPROVED_FOR_OFFLINE_ZERO_SEARCH_PLAN_CONTRACT_ONLY`。它不替代 proof-only G2、37-seed
独立事实批准、每批 fresh proof/exact G3、identity review 或 production apply 授权。

## 2026-08-30 production apply Full 工程复审

本轮按 legacy feature / Full 模式对 production apply 的规格、设计、测试、任务、rollout、settings、host wrapper、
maintenance preflight、rolling ledger/receipt/reverse 与相关项目状态文档做两轮复审。仓库没有该 legacy change 的
OpenSpec YAML/sidecar，因此不伪造状态文件；本节是当前实现者的工程自审，不替代任务清单中仍待完成的独立全
diff 代码审查。

### Round 1 findings

- `ER-PA-01 P1`：输入最终 member 是普通文件时，中间目录 symlink 仍可能绕过可信 runtime/package containment。
  已把检查边界限定为可信根以下的每个路径组件，并在 Django preflight 与 host wrapper 双层拒绝；可信根以上的
  macOS `/var -> /private/var` 系统祖先别名不误判。新增 direct/intermediate symlink 与 wrapper 合同回归。
- `ER-PA-02 P2`：`P0_HORSE_PRODUCTION_PREFLIGHT_REQUIRED` 与
  `P0_HORSE_PRODUCTION_REVERSE_ENABLED` 已存在于 settings/运维文档，但未进入 `.env.example`。现已分别以
  `true/false` 保守默认值登记。
- `ER-PA-03 P2`：`test_cases.md` 的 C13–C17 重号，且新增 maintenance/rolling receipt/reverse/database-only
  合同只出现在 design/tasks，没有逐项 requirement/test 追踪。现重编号为 C19–C23，新增 I17、K11–K20，
  并补 spec scenarios 与追踪矩阵。
- `ER-PA-04 P2`：项目总览、状态与 runbook 仍混有同日早期“ordinal/reverse/preflight 尚缺”表述。现将旧段落
  明确标记为历史 checkpoint，并把当前真实阻断统一为独立审查、最终 release/image、写前 backup、现场 fresh
  proof、精确 production apply 授权与 verifier。

### Round 2 focused re-read

- spec -> design -> test -> task -> rollout 对 production 关闭态、连续 ordinal、原子 receipt、零写 replay、
  default-off reverse、database-only 和中间 symlink 拒绝已有一一对应；测试 ID 全局无重复。
- `.env.example` 与 settings 默认值一致；reverse 不因文档登记而启用，preflight 不因旧 direct command 而降级。
- 项目级当前状态没有再把已关闭的代码缺口写成当前缺口；所有真实网络、production apply、canonical、公开发布
  和英国 TRA proof 仍保持未授权/暂停。
- 聚焦证据：受影响 Django `288/288`，host collector/wrapper `10/10`；`py_compile`、`sh -n`、Django check、
  migration drift、唯一测试 ID 与 `git diff --check` 通过。此前同一实现的隔离 PostgreSQL 16 `9/9` 仍有效；
  本轮路径与文档修正不改 DB schema/transaction code。

复审 verdict：`LOCAL_PRODUCTION_APPLY_CONTRACTS_GREEN_INDEPENDENT_REVIEW_PENDING`。

该 verdict 只表示当前实现者的两轮 Full 方案/实现一致性 findings 已关闭，不构成独立审查、commit/push/merge、
G2/G3、部署、TRA 请求、production apply、reverse、canonical 写入或公开发布授权。英国 TRA 样本与 shared
canonical 继续按 PR129 协调保持暂停。

## 2026-08-30 cross-language identity evidence 聚焦复审

### Finding

- `ER-ID-01 P1`：resolver 原先把任意双向 `HorseNameVariant.is_official=true` 当成强 official crosswalk，
  即使 evidence URL/SHA 缺失、URL 为任意第三方域、profile 没有 reviewed local key，也会在 DOB/sex/sire/dam
  之前直接 bind。proposal profile snapshot 同时遗漏 official variant 的 evidence URL/SHA、external linkage
  与有效期，因此审核后替换证据不会使旧 approval 失效。

### Resolution 与二轮复读

- 新增 authority host/namespace 与 official source/region 对齐；缺证据或错 authority 不再 direct bind。
- host-only 二轮复读仍可引用同站另一匹马，现再要求日港 authority horse-record 路由与 verified key ID 精确一致。
- 可信 link 与另一 profile 的未可信 official claim 并存时 fail closed，并保留全部候选 profile ID。
- proposal snapshot 纳入 external linkage、有效期、evidence URL/SHA；RED 已证明修复前证据替换可绕过，
  修复后 publish 阶段以 snapshot drift 拒绝。
- 新增 content-addressed production identity census，冻结 provider/external/decision/current identity/official
  claims/profile snapshots；explicit scope、重放、输入/时间/输出失败关闭和零业务写入有专项覆盖。
- spec/design/test/tasks/rollout 与项目状态/决策/runbook 已同步；H18–H25 覆盖布尔标记、证据缺失、namespace/
  authority/record-ID 错配、跨 profile conflict、post-proposal evidence drift 与 census。
- census `6/6`、聚焦 Django `44/44`、External staging -> P0 candidate -> census/identity/module review ->
  production apply/receipt 扩大相邻链 `393/393` 通过；无 migration/schema 变化，0 网络、0 DB 写、0
  production/canonical 变更。

复审 verdict：`LOCAL_IDENTITY_EVIDENCE_GATE_GREEN_INDEPENDENT_REVIEW_PENDING`。

该 verdict 是当前实现者的聚焦自审，不替代 tasks 中未完成的 production identity census、独立全 diff 审查、
部署或任何 identity/production apply 授权。

## 2026-08-30 真实 France/Ireland P0 candidate 响应边界复审

- `ER-CAND-01 P1`：fixture 只含目标 horse profile/results，真实 Westover 包的声明 parent Pro response 会被旧
  allowlist 拒绝。现要求 parent ID 先在 normalized 声明，并把 normalized/matrix/response canonical payload
  SHA 三方绑定；任一未声明 parent 或 hash drift 仍失败关闭。
- `ER-CAND-02 P1`：真实 Economics search 含澳洲同名马，采集器为 occurrence 消歧读取其 results。现仅当该
  `hrs_*` 已由同包严格 `name`/`q` search response 披露时，把它标为 discovery probe 并排除出目标证据；
  未披露 extra endpoint 继续阻断。
- Westover/Economics 候选 SHA 分别为 `64dafd20…4263` / `81afe328…2e7e`，均
  `review_required/create_new_candidate`、0 missing/conflict；双马 census manifest 为 `7cd24d0…e013`。
- candidate 专项 `13/13`、identity/module proposal `34/34`、扩大相邻链 `393/393`。没有新增网络请求，隔离 staging 不属于 production，
  canonical/identity/module/apply 全部保持未批准。
- 真实双马 identity/module proposal 已分别冻结为 `b9c2b6f7…a826` / `e9ff2689…20a5`，状态均为
  `PROPOSED_NOT_APPROVED`；建议 create/approve 不是独立决定。

复审 verdict：`REAL_RESPONSE_ALLOWLIST_GREEN_INDEPENDENT_REVIEW_PENDING`。

## 2026-08-31 pre-2005 v2/correction/rollout 方案增量复审

本轮按 `plan-eng-review` Full 模式先只读重审 spec/design/test_cases/tasks/rollout 与当前 v12 实现，再退出
审核模式修正文档，最后在同一 reviewer context 二轮复读。没有触碰生产、shared lock、Beat、registry、TRA
网络或数据库。

### Round 1 findings

- `ER-PRE2005-01 P1`：实现已经允许 651 条只有 edition year 的 `targeted-horse-seed.v2`，但 spec/design 仍把
  occurrence 强身份写成 exact date 且只描述 v1。独立审核人无法从方案判断缺日期后的候选扩大边界。
- `ER-PRE2005-02 P1`：16 条 not-held/cancelled correction 已有独立 proposal/publisher，方案却没有对应
  requirement、scenario、test、task 和 rollout 守恒；存在把 1,144 个 target 错报为 1,144 个 winner seed 的风险。
- `ER-PRE2005-03 P1`：rollout 当前检查点仍停在 2026-08-29，并保留扩容前内存 fail-closed 为当前状态，未记录
  event 956、Beat 不可停、`race_live=7543` 不动和 `740a…cff2` / `3bac…a6da` registry 分离边界。
- `ER-PRE2005-04 P2`（Round 2 审核包汇总时发现）：10 条英国 correction 没有 row-level URL/page SHA，
  只通过上游 source proposal manifest + candidate-row SHA 绑定冻结证据；初次修订把逐行 URL 写成必需，和
  可重放实现不一致。

### Resolution 与 Round 2

- spec/design 现明确 v1 精确日期与 v2 date-optional 的差异；v2 缺日期时必须使用 edition year、赛事/马场
  canonical aliases、grade、discipline 和 position 唯一匹配，0/多解及多个 horse candidate 命中均失败关闭。
- F43–F51 与追踪矩阵覆盖 v2 字段缺失、多解、proposal 不可执行、独立 source approval，以及 correction
  独立 scope/漂移/`database_apply_approved=false`。F51 明确 row-level URL 缺失时必须由上游 manifest + row
  SHA 确定性重放；全文件 258 个测试 ID 无重复。
- tasks/rollout 固定 `12,048 total / 11,935 due / 10,791 bulk-2005+ / 1,144 pre-2005 / 113 not_due`，并把
  pre-2005 守恒写成 `1,128 seeds + 16 corrections + 0 unresolved`。两类 proposal 仍分别待非实现者批准。
- rollout 当前硬门禁改为容量已通过但 event 956 仍占窗口；任何 proof 必须等 owner 明确通知后重新采集 fresh
  evidence，两个 registry 不得混用或自动迁移。
- 关闭 ER-PRE2005-04 后复读未发现新增 P0/P1/P2；完整 `runtime/research` `524/524` 通过，测试 ID 无重复，`git diff --check`
  通过。由于 change 包当前为未跟踪目录，Git diff 不作为其内容身份，最终仍须在 release 前纳入 manifest/commit。

默认批准后，1,128 seed 与 16 correction 的 exact fact-layer decision 已发布，两个首批网络 scope 的 G3 也已
发布。剩余阻断是实时并发与后续数据链条件：event 956 尚未让出赛事窗口；没有 fresh proof、TRA claim/network、
identity/module approval、backup、production apply 或公开验收。G3 不替代 fresh proof，也不允许两个账号 scope
并发。

复审 verdict：`PLAN_PRE2005_DELTA_APPROVED_EXECUTION_STILL_BLOCKED`。

## 2026-08-31 scoped reconciliation / mixed coverage 增量复审

- scoped held mode 仅缩小 target selection，不缩小 selected target 内的完整守恒；unknown source seed、scope
  漂移、count/review gap 均在发布前失败关闭。
- external Ireland seed 没有塞入 held 350-seed approval，而以独立 COMPLETE component 保留来源语义。
- mixed coverage 使用 exact occurrence key，并要求 stable set 全覆盖一次；overlap、gap、horse set 与 component
  SHA 漂移均有 RED/green 覆盖。
- planner 只消费 planning-only coverage，保持 zero-search；coverage/G3 均不授予 proof、claim、network、DB、
  identity/module 或 production apply。
- 真实 France 5 + Ireland 8 得到 13/13 coverage、3 批/2,691 GET 计划；France ordinal 1 G3 已发布但未执行。
- 聚焦回归 `25/25`，完整 `runtime/research` `532/532`，test_cases 共 263 个 ID 且无重复。event 956
  仍是当前执行门禁。

复审 verdict：`MIXED_SOURCE_PLANNING_CONTRACT_GREEN_EXECUTION_WINDOW_PENDING`。

## 2026-08-31 next-batch read-only preflight 增量复审

- claim 原有的 G3 scope、network command arguments 与批间隔验证已抽为共享校验，claim 行为不放宽。
- 新 `preflight` 读取既有 ledger，不创建 ledger/lock，不加载 exclusive proof 或凭据，不 claim，不创建
  output/budget；exact 参数通过才返回 `ready_for_fresh_exclusive_proof`。
- 正向与 command-drift 两项 RED/green 证明 ledger bytes、lock bytes、output/budget 均无变化；claim/complete/
  safe-stop 原回归继续通过。
- 真实 France ordinal 1 运行前验证通过：5 seeds、1,035 GET、results/profile/fallback only；ledger/lock SHA
  前后分别保持 `573f2ac1…9840 / e3b0c442…b855`。
- 同一实现随后对 pre-2005 France 2000 真实首批验证通过：20 anchors、320 GET、search/results/profile/
  fallback；ledger/lock SHA 前后 `8f9d51cc…a50d / e3b0c442…b855`，输出仍 absent。两种 targeted scope 没有
  混用 endpoint 或参数。
- execution-ledger 专项 `6/6`，完整 `runtime/research` `534/534`；change test_cases 共 265 个 ID 且无重复。

复审 verdict：`NEXT_BATCH_PREFLIGHT_GREEN_FRESH_PROOF_STILL_PENDING`。

## 2026-08-31 bulk-range read-only preflight 增量复审

- bulk claim 的 exact next scope 与 spacing 校验抽为共享函数，preflight 和 claim 使用同一判定；claim/proof
  语义未放宽。
- bulk preflight 只读现有 ledger，不加载 proof、不创建 output/budget、不 claim；path/scope drift 有独立
  fail-closed 测试。
- 真实 France 2005–2007 首批通过：105 targets、3 ranges、603 GET、endpoint 仅 `bulk_results`；ledger/lock
  SHA 前后为 `6c83d21a…1c47 / e3b0c442…b855`，两类输出目录仍 absent。
- bulk execution-ledger 专项 `4/4`，完整 `runtime/research` `536/536`；change test_cases 共 267 个 ID 且无重复。

复审 verdict：`BULK_NEXT_PREFLIGHT_GREEN_FRESH_PROOF_STILL_PENDING`。

## 2026-08-31 selected-scope single-command audit 增量复审

- selection v2 纳入 selected plan/G3/ledger/lock/seed/OpenAPI/output/budget 与全部运行参数；v1 SHA
  `31d3b6ee…836b` 被显式 supersede，但保留不可变历史。
- auditor 只接收 selection root+SHA，严格验证私有普通文件、COMPLETE marker、authorization=false、绝对路径、
  基线 ledger/lock SHA，再调用共享 targeted preflight；前后再次比较 SHA 和 absent dirs。
- 重复 JSON key、NaN/Infinity、布尔冒充整数、projection/SHA/path drift 均失败关闭；不会静默切 alternative。
- 真实 selection v2 SHA `366dde54…e0a6` 返回 selected France 2023 5 seeds / 1,035 GET / zero-search，
  `ready_for_event_release_and_fresh_proof`，network/DB=0。
- auditor 专项 `3/3`，完整 `runtime/research` `539/539`；change test_cases 共 270 个 ID 且无重复。

复审 verdict：`SELECTED_SCOPE_SINGLE_COMMAND_GREEN_EVENT_RELEASE_PENDING`。

## 2026-08-31 selected-batch postprocess plan 增量复审

- 生成器只接受 selection v2、execution ledger 已验证的 latest COMPLETE batch 与 exact materialization；
  ledger active、后续 completed、batch/SHA/seed/horse/run drift 都在输出前失败关闭。
- staging dry-run 与 apply 分开冻结；即使 argv 含 `--apply --allow-write`，authorization 仍固定 false，避免把
  命令可描述误读成数据库已批准。
- candidate 路径可预先绑定，但 candidate SHA 必须实际生成后计算；module review 计划保留显式 required sentinel，
  不提供伪 hash 旁路。
- 专项 `3/3`，与 selected auditor/materializer 合计 `10/10`，完整 `runtime/research` `542/542`；change
  test_cases 共 273 个 ID 且无重复。

复审 verdict：`POSTPROCESS_PLAN_GREEN_REAL_BATCH_AND_DB_GATES_PENDING`。

## 2026-08-31 materialization atomic staging 增量复审

- loader 重验 materialization marker/manifest/source batch、顺序、seed/horse/run path、单马 manifest 与 normalized
  identity；多余顶层成员和 symlink 均失败关闭。
- batch dry-run 在任何写入前覆盖全部 run；apply 使用单一外层事务复用现有单马 import receipt 与 source lock。
  synthetic 第二 run 异常后 ExternalHorse/Race/Result/History 均为 0，证明当前批新写整体回滚。
- 正常 apply 后第二次整批执行逐项 replayed；write flag、显式 allow-write 与 canonical identity=0 未放宽。
- staging 专项 `9/9`，postprocess 专项 `3/3`；change test_cases 共 276 个 ID 且无重复。

复审 verdict：`MATERIALIZATION_ATOMIC_STAGING_GREEN_REAL_DB_WINDOW_PENDING`。

## 2026-08-31 candidate-batch module handoff 增量复审

- candidate batch 只消费 exact materialization 与已写 External staging；原子发布候选文件、manifest、最后
  PREPARED，逐项绑定 seed/horse/source run/path/SHA/status/blocker。
- 全体 review-required 才 module-ready；JPN fixture 无 official crosswalk 时 batch 保持 blocked，
  `prepare-batch` 拒绝。重复 `hrs_*` 在写 output 前失败，成员 byte 漂移由 loader 拒绝。
- module `prepare-batch` 重新加载 exact batch 后复用既有单地区/identity/career/evidence 校验，没有新增审核旁路。
- candidate 专项 `17/17`，candidate + module review `29/29`；change test_cases 共 280 个 ID 且无重复。

复审 verdict：`CANDIDATE_BATCH_HANDOFF_GREEN_REAL_CANDIDATES_PENDING`。

### Identity review 同批入口补充

- identity command 现有 `--prepare-batch`，与 module loader 共用 exact candidate-batch 校验；只把已验证的
  `candidate_inputs` 交给既有 proposal service，没有复制 identity 决策逻辑。
- batch 模式显式拒绝 individual candidate 参数混入；输出仍为 `PROPOSED_NOT_APPROVED / database_writes=0`。
- identity 专项 `24/24`，staging/candidate/census/identity/module 相邻链 `90/90`。

## 2026-08-31 candidate-batch completion-audit 增量复审

- current audit 现在将 batch manifest/PREPARED、source materialization/batch SHA、全部 candidate path/SHA/size/
  source-run/status/blocker 与唯一 `hrs_*` 作为一个不可拆分输入，并拒绝额外成员与 symlink。
- identity/module proposal 继续按 candidate absolute path + exact SHA 回绑；batch 与旧逐文件输入互斥，不能混合
  两套成员后伪造守恒。
- audit 语义未放宽：输出仍固定 `AUDITED_INCOMPLETE`，production receipts/inventory/public verifier 缺失仍是硬门禁。
- 所有 JSON/JSONL/JSON marker 改为严格解析，重复 key 和 `NaN/Infinity` 不再被 Python 默认解析接受。
- 新增专项后 `11/11`，change test_cases `287/287` 唯一；用项目锁定版本临时补齐 `beautifulsoup4` 后，完整
  research `547/547`。

复审 verdict：`CANDIDATE_BATCH_AUDIT_BRIDGE_GREEN_FINAL_COMPLETION_EVIDENCE_PENDING`。

## 2026-08-31 bulk stable-ID / global authority coverage 增量复审

- 发现原 rollout 第 8 步只对 targeted materialization 有实现，10,791 个 bulk targets 的 COMPLETE output 无法进入
  stable merge；这是全量目标的真实断链，不是文档问题。
- 新 builder 复用 frozen bulk plan loader 和 reconciliation function，重新验证 exact run/plan/cache/normalized，
  只将 actual starters 投影为 v1 stable seeds；NR 与 unresolved 不进入。
- stable loader 保留 `source_bulk_run`，coverage builder 递归遍历 merged lineage，并把每个 bulk run 作为
  `provider_native_bulk_run` component 与 held/external approvals 做 occurrence-level exact union。
- 复审中删除了“单 bulk run 直接 enrichment”入口；最终路径固定为全部 ledgers merge/de-duplicate → global
  coverage → zero-search plan，防止跨批同一 `hrs_*` 重复抓取。
- 新增 read-only frontier，把每个 COMPLETE execution receipt 与固定 batch stable child 做 1:1 run/ledger/
  participant 重放；只有 32/32 且 active=null 才输出 merge inputs。planner 也独立重验 bulk source stable 属于 merged lineage。
- pre-2005 targeted 也新增 COMPLETE→full materialization→stable 两段 read-only frontier，验证固定 child/member set/
  actual-starter occurrence；只有 65/65 且 inactive 才输出该分区 merge inputs。
- 新增 provider-native targeted materialization component，重放 materialization/actual starters/source stable，并要求
  source stable 属于最终 merged lineage；planner 还逐 component 核对 binding rows 与 binding SHA。
- 最终 source selector 只组合 32 bulk + 65 pre-2005 targeted frontiers；13 马 pilot occurrences 明确排除，避免与
  bulk target 重复。只有 97/97 且两个 ledger inactive 才生成 merge argv。
- merge 后 coverage frontier 再验 v2 manifest 的 exact 97-source set，并冻结 32 bulk run + 65 targeted
  materialization component argv；不接受 pilot 或手工额外 component。
- coverage 后 plan frontier 再次重验同一 source/merged state、exact 32+65 component set、全部 occurrence/horse 与
  unique `hrs_*`；只生成 zero-search planner argv，不能用 COMPLETE coverage 手工绕过全局门禁。
- 多批 review frontier 把四个 postprocess parents 限制为 COMPLETE batch IDs 的连续前缀；proposal handoff 前重验
  materialization/source batch/run 与计划 horse union，并把 staging apply 保持为另行授权。
- 合成 bulk/targeted execution→postprocess→stable→coverage→plan→review 与相关模块 `28/28`；完整 research `558/558`，相邻 Django `90/90`，
  test_cases `300/300` 唯一。真实账本 bulk 0/32、pre-2005 targeted 0/65，网络/数据库写均为 0。

复审 verdict：`BULK_TO_GLOBAL_STABLE_ID_CHAIN_GREEN_REAL_RUNS_PENDING`。

## 2026-08-31 final global canonical inventory 增量复审

- 旧 completion audit 继续固定 `AUDITED_INCOMPLETE`；新增证据合同把最终完成拆成 global denominator、review
  approvals、canonical DB/receipts、production public verifier 四层，proposal/candidate 不再可能被误报为完成。
- 新 inventory producer 只接受 exact merged stable v2 root + manifest SHA，严格验证固定成员、marker、JSON、ledger
  bytes 与 horse/occurrence counts，再以唯一 `hrs_*` 查询 verified identity。
- verified identity 还必须由 applied、未 reverse 的 identity review receipt 覆盖并通过 identity/variant live verifier；
  手工 verified 行不能单独通过。canonical profile 复用现有 `evaluate_full_profile_completeness`，另外要求 full
  completeness、published 状态和时间；profile/career receipt 选择最后未 reverse 的有效记录并执行 live verifier。
- 两个 provider ID 指向同一 profile 时预先聚合 profile→ID set，因此两行都阻断，不受遍历顺序影响。
- 输出只有本地 `inventory/public-page-targets/manifest/marker`；authority 中 review/apply/publish/public-fetch 全为 false，
  即使 DB 层通过也固定 `completion_achieved=false`。
- inventory 专项 `6/6`、production ledger 相邻 `19/19`、identity/candidate/module/receipt 受影响链 `78/78`；完整
  research `558/558`，change test IDs `306/306` 唯一，Django check、migration check、`py_compile` 与
  `git diff --check` 通过。尚未连接生产、未读取 production DB、未发页面请求。

复审 verdict：`GLOBAL_CANONICAL_INVENTORY_GREEN_REAL_ARTIFACTS_AND_PUBLIC_VERIFIER_PENDING`。

## 2026-08-31 production public-page verifier 增量复审

- 页面合同不是“返回 200”：inventory 新增 exact required texts/headings、总履历 ID/key 顺序、分页数与主胜鞍计数；
  public template 暴露 profile/count/page/pages 与逐场 record identity，verifier 对所有页逐项比较。
- 执行拆成 immutable plan 与 fetch 两阶段。plan 严格重验 inventory member/marker/SHA/count/path，第一页与后续页 URL
  均 exact-match；prefix URL、额外 query、跨 profile 页、遗漏/重复页或 record slice 漂移全部在请求前拒绝。
- 真实命令有 CLI+env 双门禁；HTTP client 禁用环境 proxy/netrc、credentials、redirect 与 cookie 继承，固定 allowlist、
  单并发、`>=0.5s`、单页 `<=5 MiB`。这只授权公开 GET，仍无 DB/publish/production apply authority。
- 逐页原始 HTML、body SHA、status/final URL、blockers 与 aggregate SHA 均冻结。任一页失败生成
  `VERIFIED_INCOMPLETE`；即使全部通过，仍等待 final global approval/inventory/public set audit 后才可
  `AUDITED_COMPLETE`。
- 验证：新增公开 verifier/markup `8/8`，与 inventory 合并 `14/14`，Django check、migration check、`py_compile`
  与 `git diff --check` 通过；change test IDs 更新为 `314/314` 唯一。测试只使用 synthetic inventory 与 injected
  fetcher，真实 network/production DB/lock/Beat/registry/race_live 均未触碰。

复审 verdict：`GLOBAL_PUBLIC_VERIFIER_GREEN_REAL_INVENTORY_AND_NETWORK_RUN_PENDING`。

## 2026-08-31 global review aggregate 与 final audit 增量复审

- 早期“信任 synthetic review aggregate”方案已删除；最终实现要求 producer 重放 exact candidate、identity
  proposal/approval 与 module proposal/approval，按批互斥并完整覆盖 merged stable denominator。
- aggregate loader 区分 pre-apply live proposal replay 与 post-apply frozen-byte replay：producer 生成时两者都验；
  final audit 读取时重验冻结 proposal、candidate 和 approval，不把合法 identity apply 当成 proposal 漂移。
- identity receipt artifact SHA 与 production receipt module approval SHA 形成两条独立逐马 lineage；final audit 同时
  要求 review/inventory/public provider set、stable identity 与 public plan inventory binding exact 相等。
- 只有 final audit 能写 `AUDITED_COMPLETE / completion_achieved=true`。inventory/public complete、HTTP 200、单个
  approval 或比例接近都不能升级；失败时输出目录不存在。
- 验证：专项 `2/2`，受影响 candidate/identity/module/production-ledger/inventory/public/final 链 `114/114`，完整
  research `558/558`，Django check、migration check、`py_compile` 与 `git diff --check` 通过。
  change test IDs 更新为 `319/319` 唯一。全部使用 synthetic/injected evidence；没有生产 DB、网络、lock、Beat、
  registry 或 race-live 操作。

复审 verdict：`FINAL_AUDIT_CONTRACT_GREEN_REAL_GLOBAL_ARTIFACTS_PENDING`。

## 2026-08-31 global approval binding 自动化增量复审

- 原 runbook 仍要求操作者为全部 enrichment batches 人工拼 `batch-bindings.jsonl`，存在漏批、错 SHA 与混入 pilot
  的操作风险。新 producer 直接以 complete/inactive execution ledger 固定批次顺序，并要求六类 parent child set
  各自 exact-match plan IDs。
- producer 逐批重放 materialization/candidate/proposal 守恒，再核对 identity/module approval 的 exact
  marker/member/proposal/decision/horse set；跨批 `hrs_*` 必须互斥，execution ledger 在生成期间不能漂移。
- 输出只是 immutable wrapper，aggregate 仍须通过 root+manifest SHA 严格重载并独立重放全部 child；因此 wrapper
  不能伪造 approval authority，也不会把人工清单变成新的信任根。
- 验证：producer `6/6`、Django wrapper/command/aggregate `3/3`；全部 synthetic/filesystem-only，未访问生产网络、
  DB、lock、Beat、registry 或 race-live。

复审 verdict：`AUTOMATIC_BINDING_CONTRACT_GREEN_REAL_COMPLETE_BATCHES_PENDING`。

## 2026-08-31 proposal→approval frontier 增量复审

- 原 postprocess status 只能证明 proposal 齐套，不能表达 identity/module approval 的逐批进度。新 frontier 复用原
  exact candidate/proposal replay，再把 approval parents 约束为 validated proposal IDs 的连续前缀。
- 为避免全量网络完成后才开始人工审核，已完成 proposal prefix 可以流水线进入 review；但 identity decisions 与四模块
  source-record 判断仍要求 reviewer evidence，publisher 绝不自动运行。
- identity rows 进一步按 verified provider ID、official/local crosswalk、strong biodata、observed ID、create-new
  跨语言防重与 ambiguous/blocked 分组。分类只优化审核队列，不改变动作或降低证据要求；全部仍需人工 review。
- 已存在 approval 通过 automatic binding producer 的严格 loader 重验；只有全量双审齐套时，才授权 network/DB=0
  的本地 binding artifact generation。该授权不传播到 identity/production apply。
- 验证：专项 `9/9`，并以真实 13 马零状态证明 3 planned、0 proposal/approval/output、authority 全 false、future
  parents 未创建。完整 research 更新为 `573/573`，change test IDs `329/329` 唯一。

复审 verdict：`APPROVAL_FRONTIER_GREEN_REAL_REVIEW_DECISIONS_PENDING`。

## 2026-08-31 module proposal replay 完整性增量复审

- 发现：module proposal loader 原先验证 rows/manifest SHA 与计数，但没有像 identity proposal 一样从 candidate bytes
  重建 row。同步重算 rows、manifest 与 marker 后，publisher 可能接受被改过的人审摘要。
- 修复：prepare/load 共用 deterministic manifest builder；load 逐行打开 exact candidate SHA、重跑完整 candidate
  validator、排序重建 rows，并要求 rows 与 manifest 都精确相等。global aggregate 复用同一 loader，因此已发布链也会
  在聚合时再次 replay。
- module/identity JSON/JSONL loader 同步拒绝 duplicate key 与 `NaN/Infinity`，避免内容寻址 artifact 存在多 parser 解释。
- 验证：rehashed `recommended_decision`、ambiguous module JSON 与 non-finite identity decision RED→GREEN；module
  `14/14`、identity `25/25`、相关 service 链 `87/87`、完整 research `573/573`，change test IDs `332/332` 唯一，
  Django/migration/compile/diff 绿色。无生产动作。

复审 verdict：`MODULE_PROPOSAL_REPLAY_GREEN_REAL_REVIEW_BATCHES_PENDING`。

## 2026-08-31 materializer/staging strict JSON 增量复审

- 发现：内容寻址 materializer/staging 会验证 SHA、size、marker 与成员集合，但部分 `json.loads` 仍接受 duplicate key
  和非有限常量；同步重算 SHA 后可形成多 parser 解释。
- 修复：materializer 的 batch/content-pool/run/compact/seed reader，以及 staging 的 run/materialization/response/
  normalized reader，统一使用 strict object-pairs 与 non-finite rejection。歧义在 dry-run 和 DB transaction 前失败。
- 验证：materializer `5/5`、staging `10/10`、完整 research `574/574`、change test IDs `333/333` 唯一；approval
  相关 service 链 `87/87` 保持绿色，Django/migration/compile/diff 绿色。无生产动作。

复审 verdict：`STAGING_STRICT_JSON_GREEN_REAL_MATERIALIZATIONS_PENDING`。

## 2026-08-31 网络与批次 ingress strict JSON 增量复审

- 发现：下游 materializer/staging 已严格解析，但最早的 provider HTTP response（含 credential diagnostic）、OpenAPI/seed、bulk target 与 targeted
  batch input 仍可能由 Python 默认 decoder 接受 duplicate key 或非有限常量；一旦先形成 cache/plan artifact，风险已越过
  正确的失败边界。
- 修复：network client、reviewed fingerprint/seed、bulk target manifest/JSONL、targeted seed
  ledger/batch-definition/checkpoint 统一使用
  duplicate-key/non-finite rejection。内容 SHA、manifest SHA 与 COMPLETE marker 同步重算仍不能绕过。
- 验证：auth diagnostic `3/3`、horse exporter `42/42`、bulk+targeted batch `17/17`、完整 research `579/579`、
  change test IDs `338/338` 唯一；candidate/identity/module/global/staging Django 链 `97/97`。event 956 未释放，
  本轮无生产动作。

复审 verdict：`STRICT_INGRESS_GREEN_REAL_NETWORK_BATCHES_PENDING`。

## 2026-08-31 当前年度日期老化增量复审

- 发现：target catalog as-of 固定于 8 月 29 日时，下游工具原先要求 execution as-of 完全相等，导致 8 月 31 日无法
  合法淘汰 4 条已经过赛日的 `not_due`；继续沿用旧 artifact 会把 due 分母少算 4。
- 修复：calendar/coverage/bulk execution as-of 可在同一 catalog 年内单调向前；occurrence compiler 同步允许该推进，
  但拒绝更早/跨年日期、non-held as-of 不一致和 `local_date <= execution as-of` 的陈旧 not_due。
- 重放：当前分母为 12,048 total / 11,939 due / 10,795 bulk / 1,144 targeted / 109 not_due；completion
  audit v4 仍为 `AUDITED_INCOMPLETE`，11,589 due gap、provider IDs approved=0。
- 计划：新 bulk plan 仍 32 batches/21,708 GET ceiling；旧 G3 因全局 plan SHA 改变不可复用，新 ordinal-1 仅有
  `PROPOSED_NOT_APPROVED` proposal，无 proof/claim/network/DB。
- 验证：专项 `36/36`、完整 research `584/584`、相关 Django `106/106`、test IDs `341/341` 唯一，
  check/migration/compile/diff 全绿。event 956 生产边界未改变。

复审 verdict：`TEMPORAL_AS_OF_GREEN_REAL_EVENT_WINDOW_PENDING`。

## 2026-08-31 bulk range page checkpoint/resume 增量复审

- 发现：range runner 原先只有 batch 级 safe-stop。真实请求若在多页区间中断，execution ledger 能记录消耗但没有
  可信 page checkpoint，既不能安全重试，也不能证明不会重取前页；因此真实首批前仍有 P1 恢复缺口。
- 修复：每个成功页先原子保存 response wrapper 与 exact receipt，再更新 strict checkpoint；definition 绑定
  plan/OpenAPI/ranges。resume 重验全部 cache/member/count，只从下一 skip 继续，并把 client ceiling 缩为剩余额度。
- 修复：execution ledger 新增显式 resume，要求原 exact approval、fresh proof、同 output/account/OpenAPI；完成
  receipt 继承 safe-stopped attempts，当前 attempt 只记录增量请求，entry 保存累计值。stable-ID builder 再次重验
  definition/checkpoint 和 retry-aware request/response lineage。
- 验证：新增 F137–F139；模拟第二页失败后从 skip 100 续跑、cache/definition/prior-count 漂移零联网拒绝、过期
  proof 拒绝及两 attempt 累计完成。bulk runner/ledger 专项 `13/13`、完整 research `587/587`、相关 Django
  `106/106`、test IDs `344/344` 唯一，check/migration/compile/diff 全绿。
- 生产边界：event 956 后续补充授权 selected France 2023 真实关闭态；该 scope 已 5/5、19 GET COMPLETE 并恢复
  exact PR133 后释放锁。bulk 本节仍没有 claim/proof/TRA 请求/DB 写，registry 与 `race_live=7543` 未动。

复审 verdict：`BULK_PAGE_RESUME_CONTRACT_GREEN_SELECTED_PROOF_CLOSED_STATE_AUTHORITY_PENDING`。

## 2026-08-31 selected France 2023 真实窗口执行复核

- event owner 的补充授权覆盖同一随机-token lock 内的临时 fail-closed、唯一 France 2023 scope 与 exact 恢复；
  pre-2005/bulk/UK/USA、production DB 和 registry 写入继续禁止。
- 首次 retry 暴露 account scope/G3 approval SHA 混用并在 claim 前失败；修正为 proposal SHA 后，fresh proof
  `491c422c…6d38` 通过。runner 最终为 5/5 seeds、19 GET、0 DB writes，batch/marker `ed0295d9…f7973`，
  execution ledger active=null。
- restore 脚本在错误 `/health/` 断言处非零，但锁被保留；独立终验使用正确 `/healthz/` 后确认 exact PR133、
  10 flags true、双 registry、leaf 0075、Web 1x4、两个 worker、Beat、Nginx、queues 与 event 956 均正常，再由
  原 token release。这个失败没有被 HTTP 200 或脚本局部输出误报为完整恢复。
- 全量 materialization `f7a1fa5e…51b99` 与 postprocess plan `90d5613f…e2f61` 已生成；计划仍固定
  `PREPARED_NOT_AUTHORIZED`，数据库和公开链保持未批准。

复审 verdict：`SELECTED_FRANCE_2023_COMPLETE_RESTORED_POSTPROCESS_PREPARED_DB_GATES_PENDING`。

## 2026-09-01 latest-main 续跑 Full 工程复审

审查 profile：`feature / Full`。本轮在 latest main 干净 worktree 重建可执行依赖闭包，并重读 proposal、spec、
design、tasks、test cases、rollout、TRA runtime、账本与恢复合同。历史 dirty worktree 只作来源证据，没有重置、
覆盖或直接执行其中的旧计划。

### 第一轮 findings

#### ER-20260901-01 P1：官方 OpenAPI selected schema 已漂移

旧冻结 fingerprint 选择 `HorseStandard`；2026-09-01 两次读取官方 OpenAPI 的 full bytes 均为
`0033643fcca4301889098fe6dcda021beb840207880f848a25b6153208a87df7`，版本仍为 1.4.4，但 standard horse
path 现引用 `Horse`。继续携带旧 selected schema 会使真实网络在 client 前失败，或诱使操作者跳过 fingerprint。

修正：新增 deterministic capture 工具，严格解析 raw OpenAPI、固定 full/path/schema SHA、operation plan 与 rate，
review artifact 精确绑定本地 fingerprint；runtime selected schema 改为 `Horse`，旧 fingerprint 继续因 SHA 漂移失败关闭。

状态：已关闭。

#### ER-20260901-02 P1：年度/半年 range plan 违反 provider 的单日查询建议

设计写明按日期分区，但历史实现把一个 region-year 聚合为年度或半年 `start_date/end_date` range。官方 results
说明明确建议每次查询一个日期；长 range 会放大深分页、响应漂移、proof 到期和 resume 成本。

修正：readiness 固定输出 `start_date=end_date` 的地区日分区；本次 2005-01-01 至 2026-08-31 共 31,656 个 ranges，
由 88 个 region-year batches 聚合。每个地区日 fail-closed 最多 10 页，runner 保留逐页 cache/checkpoint；
异常或 proof 到期时只从下一页 fresh-proof resume。

状态：已关闭。

#### ER-20260901-03 P2：变更包缺 proposal，现行合同写死旧 32+65 分母

变更目录只有 design/spec/tasks/rollout/test cases；现行合同又把历史 32 批计划写成 97-source 固定不变量。
按日 plan 变为 88 批后，即使 runtime 已动态读取 plan，文档与验收仍会错误阻断合法 153-source merge，或让操作者
误执行旧 G3。

修正：补 proposal，明确目标、范围、非目标、风险和完成口径；现行合同统一改为 frozen-plan `N_bulk+65`，
本次实例明确为 88+65=153。历史 32-batch artifact 保留且标注不可执行，不篡改历史 SHA 事实。

状态：已关闭。

### 第二轮复审

- 架构/数据流：target denominator、bulk/targeted 双入口、stable-ID merge、zero-search enrichment、External staging、
  identity/module review、canonical apply 与 public verifier 边界完整；没有用 provider 返回反推应到总账。
- 数据模型/迁移：本轮只引入 artifact runtime 与文档，无 model/migration 变化；`makemigrations --check --dry-run`
  为 `No changes detected`。
- 并发/恢复：账号级 limiter 4 req/s、单并发、request ceiling、proof/G3/claim、逐页 checkpoint 与 fresh-proof resume
  均在请求前绑定；safe-stop 不丢累计请求，不清理队列。
- 身份/权限：provider `hrs_*` 仍为主键；日港本地名/海外英文名只通过 authority crosswalk 与强生物信息审核，
  名称单键不能合并。staging 不授予 canonical/public 权限。
- 测试：全部 research discovery `319/319` 通过；本轮新增/迁移的 22 个测试模块 `160/160` 通过；Django check
  0 issue；全部新 Python 模块 `py_compile`、migration check 与 diff check 通过。测试只使用 fixture/injected evidence，
  本轮复审没有 TRA 网络请求、生产 DB 写或队列操作。

剩余工作是执行而非方案缺口：88 个 2005+ bulk 批、65 个 pre-2005 targeted 批、全量 stable enrichment、审核、
staging/canonical apply 与最终公开验收仍须依账本逐批完成，不能因本次 review 绿色而宣称数据目标完成。

复审 verdict：`APPROVED_FOR_SEQUENTIAL_EXECUTION_WITH_EXISTING_RUNTIME_GATES`。
