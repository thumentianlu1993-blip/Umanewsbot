# 四地区分级赛参赛马回填任务

## 0. 基线与方案

- [x] (operations) 从最新 origin/main 创建独立干净 worktree，保留主工作区全部用户改动
- [x] (operations) 只读核对生产代码 SHA、目标账本、赛事/赛果、P0 profile 完整度
- [x] (integration) 核对 TRA 最新 OpenAPI、覆盖、套餐、限速与条款
- [x] (application) 盘点单马页字段、HorseProfile/HorseRaceRecord 与 P0 apply 链
- [x] (integration) 锁定四地区、两段年份等级、flat+jumps、actual starters 和双入口方案
- [x] (operations) 完成首轮工程审查并关闭架构、迁移、性能、失败模式 findings
- [x] (operations) 修正实现期复审发现的来源覆盖矩阵、rollout 过时状态与测试 ID/追踪关系

## 1. 爱尔兰与目标总账

- [x] (integration) 先写 IRE flat/jumps/page-boundary/declared-count RED tests
- [x] (application) 先写 RacingRegion Ireland、Europe/Dublin 与 choices migration RED tests
- [x] (integration) 实现 TJCIS Ireland parser、region adapter、稳定 series key 与统计
- [x] (integration) 在全部年份汇总后全局消歧同名 series，并重建/重审所有 SHA 绑定下游 artifact
- [x] (application) 实现 Ireland choices 和所有地区/时区合同
- [x] (integration) 从冻结 2000–当前 Blue Book caches 生成四地区筛选 ledger（冲突时仅 PREPARED）
- [x] (integration) 生成 GB/IRE/FR/USA 逐年/grade/discipline census 和 source conflict bundle
- [x] (integration) 实现 series/year target 与 held occurrence 分层、同系列同年多场不折叠和双向 gap
- [x] (integration) 接入 TOBA 2000–2024 held history parser、冠军 anchor 与 Equibase result identity
- [x] (integration) 用冻结 BHA/France Galop 2026 赛历生成双向 PREPARED 审计并关闭名称、场地、OCR 距离和等级误配
- [x] (integration) 哈希审计旧英国/法国 detail bundles，区分 exact、alias review、parse gap 与 actual result rows
- [x] (integration) 生成逐 target 的机器可读来源覆盖计划，显式区分 current-held、待审核、待重绑、calendar-only 与 route-only
- [x] (integration) 实现 reviewed COMPLETE 后才可生成 targeted-horse winner seed ledger 的 fail-closed 桥
- [x] (integration) 审核并关闭 9 个当前范围 blocker，保留 17 个非范围 conflict 记录，发布 12,048 行 reviewed COMPLETE ledger
- [x] (integration) 生成 TOBA physical/unique source、flat/jumps target 双向守恒且 hash-bound 的不可执行审核提案
- [ ] (integration) 独立审核并发布 TOBA occurrence alias/grade/reused-source approval，使美国 flat 双向 unmatched 为零
- [x] (integration) 接入 reviewed 2026 BHA/France Galop 官方赛历，将 113 个未来 target 生成 not_due occurrence 输入
- [x] (integration) 合并 reviewed held evidence 的同 target/date 多来源引用，并生成 350 held + 113 not_due 的四地区局部 occurrence 总账
- [x] (integration) 将当前年度执行 as-of 推进到 2026-08-31，淘汰 4 条已过赛日 not_due，并生成 350 held + 109 not_due + 11,589 unaccounted 的新 PREPARED 总账
- [x] (integration) occurrence compiler 允许同年执行日期向前推进，并拒绝更早/跨年 as-of、non-held as-of 漂移和陈旧 not_due
- [x] (integration) occurrence compiler 只消费 manifest/marker 绑定 proposal，并阻止未批准完整输入生成 COMPLETE
- [x] (integration) 实现独立 reviewer exact-SHA occurrence-input approval publisher；当前两个输入仍待审核
- [ ] (integration) 接入 BHA/HRI/France Galop 全历史 held/not-held occurrence 输入并完成四地区守恒
- [x] (integration) 为跨年补赛实现显式 evidence override，默认拒绝无审核或日期不绑定的 occurrence
- [x] (integration) 用 Sky Sports Wayback 完整赛果 + RTE 取消报道生成 2015 Finale Juvenile Hurdle PREPARED 替代提案
- [x] (integration) 为 11 个英国 legacy alias 生成 exact-series、hash-bound、不可执行的审核提案
- [x] (integration) 审核 11 个英国 legacy alias，并在 COMPLETE target 后审核/签署 Finale 跨年提案
- [ ] (application) 先写旧记录 Ireland reclassification prepare/dry-run/apply/verifier tests
- [ ] (application) 实现 SHA 绑定的 Ireland reclassification artifact，默认只读

## 2. TRA 离线合同

- [x] (integration) 先写 allowlist、认证脱敏、timeout/redirect/body/schema RED tests
- [x] (integration) 先写 401/403/429/5xx、Retry-After 和 endpoint-local safe-stop RED tests
- [x] (integration) 先写账号级 exclusive/shared budget、并发、崩溃和时钟回退 RED tests
- [x] (integration) 先写 results/profile/horse-results 分页与 stalled/total drift RED tests
- [x] (integration) 先写 HorsePro/Horse/ResultStandard/RunnerStandard fixture parser tests
- [x] (integration) 先写 status、country suffix、ID prefix、Pro 404 fallback tests
- [x] (integration) 实现单 run artifact-only TRA client、cache、ledger、checkpoint/resume
- [x] (integration) 实现账号级 limiter 和跨 seed/run 内容寻址 object pool
- [x] (integration) 实现纯离线 profile/result/runner normalizer
- [x] (integration) 固化 OpenAPI selected endpoint/schema fingerprint
- [x] (integration) 三个网络入口在预算、claim、client 和首个请求前校验 SHA-bound 本地冻结 fingerprint
- [x] (integration) 每个 live endpoint 响应在下一请求前执行 search/profile/results 专用 schema/pagination 校验
- [x] (integration) 从官方 `/openapi.json` 确定性捕获并复核 2026-09-01 selected fingerprint；确认版本 1.4.4、
  full SHA `0033643f…df7`、standard schema 从旧 `HorseStandard` 漂移为 `Horse`

## 3. 双入口赛事与参赛马导出

- [x] (integration) 先写 bulk date partition、region、race match、actual starter RED tests
- [x] (integration) 实现 bulk_results target runner 与逐日分页
- [x] (integration) 先写 targeted seed、search 多候选、强身份与 race reconciliation RED tests
- [x] (integration) 实现 targeted_horse runner、批次 checkpoint/resume 和 Montjeu 离线 acceptance fixture
- [x] (integration) 实现目标赛事 actual starters 到唯一 `hrs_*` 稳定 ID 总账及无 search 的二阶段补全
- [x] (integration) 实现外部历史 winner anchor 到 targeted-horse seed 的审计链，拒绝 PREPARED target
- [x] (integration) 实现批量外部 winner-anchor 的 SHA 索引、不可执行提案与独立审核发布器
- [x] (integration) 将 Ireland-specific IrishRacing 冻结页面接入离线 detail adapter；不冒充 HRI 官方 parser
- [x] (integration) 将 runner v2 扩为六地区 recipe；HRI 保留官方但阻断，IrishRacing host/path 是唯一可执行回退
- [x] (integration) 生成 1,957 行 Ireland runner readiness 审计，逐 target 显式保存 official/fallback URL gap
- [x] (integration) 将 350 个 reviewed held target 拆为 311 COMPLETE seed 复用 + 37 新增 + 2 替换 France Galop winner 候选
- [x] (integration) 实现 held-winner seed extension 独立批准发布器；输入重放与 exact-output SHA 失败关闭
- [x] (integration) 从 350 条 reviewed held evidence 重建 3,192 行 actual-starter occurrence census，排除 94 条 withdrawn/NP
- [x] (integration) 保留 PU/F/UR/BD/DNF 与 official unclassified finish，同名跨场不合并且 provider horse ID 保持空
- [x] (integration) 实现 census slot -> TRA `hrs_*` PREPARED reconciliation；同时绑定独立批准的 COMPLETE 350-seed artifact
- [x] (integration) 实现零 gap reconciliation 独立批准发布器；重放全部输入并逐字绑定 proposal/output/decision SHA
- [ ] (operations) 独立审核并批准 39 条 France Galop winner seed extension（37 新增 + 2 替换错误旧 winner）；不得由实现者自批
- [x] (integration) 实现 target <-> TRA race candidate/review mapping
- [x] (integration) 实现 race_id/hash 去重、revision conflict 与 participant occurrence artifact
- [x] (application) 先写 TRA normalized bundle 到 External staging receipt 的 RED tests
- [x] (application) 实现受 admission guard 保护的正式 RaceEvent/Runner/Result 桥
- [x] (application) 新增 manifest-bound graded_horse_backfill import layer，保持旧层合同不变
- [x] (operations) 生成首次真实 proof 的精确 G3 host/path/scope/request ceiling 包
- [x] (operations) 生成 313 个 reviewed winner-anchor 的 24 批离线计划与四地区 4 匹样本提案
- [ ] (operations) G3 后执行 Montjeu + 四地区小样本，只输出脱敏 coverage/字段非空率/请求证据

## 4. Staging 与身份

- [x] (application) 先写 ExternalDataSource/ExternalHorse 扩展 migration 和模型 RED tests
- [x] (application) 先写 HorseExternalIdentity/HorseNameVariant 基础约束 RED tests
- [x] (application) 实现最小 schema、migration 与 admin/只读检查
- [x] (integration) 实现 normalized artifact -> External staging prepare/dry-run/apply
- [x] (application) 先写生产 identity census、provider ID、official crosswalk、四字段 RED tests
- [x] (application) 实现 bind/create/ambiguous/blocked identity 只读 mapping
- [x] (integration) 接入现有 JRA/JBIS/HKJC identity evidence，禁止名称单键
- [x] (application) 收紧 official crosswalk：要求 evidence SHA、authority host/namespace 对齐并把证据漂移纳入 snapshot
- [x] (application) 实现 reviewed mapping 与 split/reject 审计
- [x] (application) 实现 identity review receipt、apply/replay、reverse ledger 与 verifier
- [x] (application) 实现 TRA candidate 的 SHA-bound career authority/module review proposal、approval 与 research bridge

## 5. 单马资料、血统与完整生涯

- [x] (integration) 先写 Pro/Standard、parent pool、最大深度和批次内全局请求去重 RED tests
- [x] (integration) 实现 artifact 层 profile、二代血统 enrichment 与批次级 GET/parent pool 去重
- [x] (integration) 先写 full horse results total/分页/race 去重/目标行抽取 RED tests
- [x] (integration) 实现完整 provider career artifact 与 gap classification
- [x] (application) 先写 artifact page field matrix 与 trainer/owner as-of candidate RED tests
- [x] (application) 先写 canonical apply 的 manual lock/人工覆盖不被改写 RED tests
- [x] (application) 先写 HorseRaceRecord 接管/幂等/状态/major wins/stats RED tests
- [x] (application) 扩展现有 participant release bridge 到多年四地区 scope
- [x] (application) 复用共享 HorseRaceRecord upsert 生成 profile/pedigree/career/major wins 模块
- [x] (application) 区分 provider_profile/page_profile/provider_career/authority_career/local_identity 状态
- [x] (application) 用真实法国/爱尔兰包收紧 candidate response allowlist：声明 parent 精确绑定、同包 search 披露的消歧 results 只读排除
- [x] (application) 在隔离 staging 生成 Westover/Economics 零写候选与显式双马 identity census

## 6. 生产 apply 与验证

- [x] (application) 先写 reviewed release manifest、SHA、symlink/path RED tests
- [x] (application) 为最终 reviewed release/package 补 exact member manifest 与 extra-file 拒绝 RED tests
- [x] (application) 先写 P0 dry-run 零写、同 artifact 幂等重放零业务写 RED tests
- [x] (application) 为 profile/career apply 补独立批次 ordinal、completed receipt 与 resume RED tests
- [x] (application) 先写 SQLite 原子性与 PostgreSQL 专用并发/rollback tests
- [x] (application) 在隔离 PostgreSQL 16 运行并冻结并发/rollback/ordinal claim `9/9` 绿色证据
- [x] (application) 扩展 P0 prepare/dry-run/apply/verifier 接受本 change scope
- [x] (operations) 实现 winner-anchor 离线 batch plan；保持网络执行默认关闭
- [x] (operations) 实现逐批 exact G3、唯一 claim、严格 ordinal/间隔和累计 retry 预算的网络 execution ledger
- [x] (operations) 实现 production apply maintenance preflight，并阻断 active import/claim/竞态写入
- [x] (application) 为 profile/career canonical apply 实现 append-only receipt 与 exact reverse ledger
- [x] (operations) 拒绝 production apply 输入路径任一中间 symlink，并补 wrapper/preflight 回归测试
- [x] (operations) 在 `.env.example` 登记 preflight 默认必需、reverse 默认关闭的保守配置
- [x] (operations) 接入账号级 TRA 共享预算；过渡期 preflight 阻断任一并发 TRA caller
- [x] (operations) 实现 host + Django/DB/Celery/Redis 双证据的限时 exclusive-account proof generator
- [x] (operations) 将 proof generator 隔离为 latest-main、零 migration 的 5 文件 proof-only G2 候选并完成两轮方案审查
- [x] (operations) 运行 migration check、Django check、聚焦测试、受影响完整测试、diff check
- [ ] (operations) 完成只读独立审查并关闭 P0/P1/P2 findings
- [ ] (operations) 固化 commit SHA、镜像、migration、artifact/manifest SHA、命令和回滚的 G2 包
- [ ] (operations) 用户 G2 后 commit/push/PR/merge/deploy代码，常驻开关保持关闭
- [ ] (operations) 用户精确 G2 后先发布 proof-only 候选，现场生成 fresh proof 并执行既有 Montjeu N1 G3

## 7. 持续导出与落表

- [x] (integration) 冻结 12,048 target 分区并按 2026-08-31 刷新：11,939 due = 10,795 个 2005+ bulk target + 1,144 个 pre-2005 target，另有 109 not_due
- [x] (integration) 将 pre-2005 readiness 收敛为 1,128 winner anchors + 16 calendar corrections + 0 unresolved，并固化三份互斥 ledger
- [x] (integration) 生成 date-optional `proposed-targeted-horse-seed.v2` 与独立 source-anchor publisher；proposal schema 不可直接执行
- [x] (operations) 按项目默认批准授权发布 1,128 条 `targeted-horse-seed.v2 / COMPLETE`；artifact 继续固定 network execution 未批准
- [x] (integration) 生成 16 条独立 calendar correction proposal/publisher，并保持 database apply 默认未批准
- [x] (operations) 生成 seed/correction exact-SHA 独立审核交接与拒绝条件；decision 模板保持不可签署 null 状态
- [x] (operations) 按 correction-only scope 发布 16 条取消/未举行结论；数据库 apply 继续为 false
- [x] (operations) 为 1,128 seeds 生成 65 批/18,048 GET 定向计划，并为 ordinal 1 France 2000 发布 exact G3
- [x] (operations) 为 2005+ bulk ordinal 1 France 2005–2007 发布 exact G3；未生成 proof 或 claim
- [x] (operations) 日期刷新后按 provider 单日建议重建 10,795-target/88-batch bulk plan；31,656 个地区×日期分区，
  旧年度范围 G3 不复用，新 ordinal 1 尚未生成 proof/claim
- [x] (integration) 让 partial stable-ID readiness 消费并重验 held 350-seed COMPLETE 与 Ireland external census COMPLETE；2/2 occurrence seed approved，execution 仍阻塞于 reconciliation
- [x] (integration) 实现 stable-scope-only held reconciliation；只选择 stable ledger 引用的 held target，所选 target 仍逐马零 gap 守恒
- [x] (integration) 实现 held COMPLETE + external single-race COMPLETE 的 mixed-source occurrence coverage；overlap/gap/SHA drift 失败关闭
- [x] (operations) 发布 France 5 马 scoped reconciliation approval，并与 Ireland 8 马 approval 合并为 13/13 planning-only coverage
- [x] (operations) 为 13 匹唯一 `hrs_*` 生成 3 批/2,691 GET 零 search 计划及 France ordinal 1 exact G3；未 proof/claim/network
- [x] (operations) 实现并真实运行 next-batch 零写 preflight；精确 G3/命令通过且 ledger/lock SHA 前后不变
- [x] (operations) 将零写 next-batch preflight 扩展到 bulk range；France 2005–2007 的 105 target/603 GET exact scope 通过
- [x] (integration) 为 bulk range 实现逐页 cache/checkpoint 与显式 resume；失败请求累计计费、剩余额度、fresh proof、多 attempt completion receipt 和 drift-before-network 已专项验证
- [x] (operations) 对 pre-2005 France 2000 的 20-anchor/320-GET exact G3 运行真实零写 preflight；与 zero-search stable scope 分离
- [x] (operations) 冻结首个 live scope selection：France 2023 stable enrichment；exact-SHA 绑定三套候选且不授权 proof/network/DB
- [x] (operations) 发布 selection v2 全路径/参数身份，并实现 root+SHA 单命令 auditor；真实 selected preflight 与 ledger/lock 零写通过
- [x] (integration) 实现 selected COMPLETE batch 的零写后处理计划器；冻结 materialized run 到 staging/candidate/census/module-review 参数且不授权写入
- [x] (application) 实现完整 materialization 的全批 dry-run 与原子 External staging apply；后段失败整批回滚、单马 receipt 可幂等 replay
- [x] (application) 实现 exact candidate batch 与 identity/module review prepare-batch；blocker/重复 hrs_*/member drift/输入混用整批失败关闭
- [x] (integration) 让 current completion audit 直接绑定 exact candidate batch，并与 identity/module proposal 做成员守恒；继续明确 incomplete
- [x] (integration) 实现 COMPLETE bulk run 到 stable-ID ledger 的确定性桥；重算 reconciliation 并守恒 plan/cache/normalized/actual starters
- [x] (integration) 将 provider-native bulk run 纳入 merged stable occurrence coverage；强制全局 merge/de-duplicate 后再规划 enrichment
- [x] (operations) 实现 bulk COMPLETE receipt → stable ledger 一一只读 frontier；仅冻结 plan 全部批次齐套且 active=null 才输出全局 merge inputs
- [x] (operations) 实现 pre-2005 targeted COMPLETE → full materialization → stable ledger 两段一一 frontier；仅 65/65 齐套才输出 merge inputs
- [x] (integration) 将 provider-native targeted materialization 纳入 global occurrence coverage，并独立重验 source stable merged lineage
- [x] (operations) 固定最终 global merge 来源为冻结 plan 的全部 bulk + 65 pre-2005 targeted；本次 88+65，组合 frontier 明确排除重复的 13 马 pilot occurrence ledgers
- [x] (operations) 实现 merge 后动态 exact-source conservation 与 coverage argv 门禁；本次固定 88 bulk-run + 65 targeted-materialization components
- [x] (operations) 实现 coverage 后 exact 153-component enrichment-plan readiness；只输出 unique `hrs_*` zero-search planner argv
- [x] (operations) 实现多批 enrichment COMPLETE→materialization→candidate→identity/module proposal 的连续前缀守恒 frontier
- [x] (application) 实现 exact merged `hrs_*` → verified identity/full profile/latest receipt 的全局只读 canonical inventory 与 public-page target artifact
- [ ] (integration) 用真实 TRA target occurrence 运行 reconciliation 并独立审核 3,192 个 starter slots，关闭 unknown/ambiguous
- [x] (operations) 从冻结 target 计算 88 个按日 bulk 批次、每批 request ceiling/时长/输出目录；plan SHA
  `49f1bdbe…982a`，执行前仍逐 ordinal 生成 exact G3/proof
- [x] (operations) 实现 approved stable-ID census 的零 search 补全批次计划器，并把 execution G3 endpoint scope 缩到 results/profile
- [x] (operations) 为旧 313 个 COMPLETE winner-anchor 生成 24 批计划；另有修正后的 350-seed/26 批投影待 39 条扩展批准
- [ ] (operations) G3 后按 region/year target batch 执行网络导出，持续写 checkpoint/summary/gap
- [ ] (integration) 对获批的 1,128 条 pre-2005 seed 和后续 bulk gap 逐批取得 fresh proof/exact G3 后运行 targeted_horse
- [ ] (integration) 对全部唯一 hrs_* 执行真实 profile/parent/career enrichment（离线 runner 已完成）
- [ ] (application) 逐批生成 identity/module review，关闭 ambiguous/unreviewed
- [x] (application) 实现真实批次可复用的 authority/module review 工具；真实逐批审核仍待网络 candidate
- [ ] (operations) 每个 production apply 窗口前生成并验证 custom-format backup
- [ ] (operations) 按 reviewed batch plan apply，每批立即 verifier 和页面抽检
- [ ] (operations) 失败时 safe-stop；修复后只从最后 completed receipt 续跑
- [ ] (operations) 当前年度按正式赛果滚动追加直到年度结束
- [ ] (operations) 对所有 provider/source/identity gap 继续替代来源/人工批次，最终 unresolved=0

## 8. 最终验收与文档

- [x] (operations) 实现并运行当前完成度只读审计，逐层绑定 target/coverage/occurrence/starter/candidate/review exact SHA，并冻结 `INCOMPLETE` 基线
- [x] (operations) 定义最终四层完成证据合同，明确旧单批次 audit 不得替代全局 approval/receipt/DB/public verifier
- [x] (application) 实现 canonical inventory 与全量 public target 只读生成器，并核验 identity/production receipt live after-state
- [x] (application) 实现公开页机器 identity、逐页 immutable plan、CLI+env 双门禁执行器与完整 response evidence
- [x] (operations) 实现 final global audit，将 global approvals、inventory receipts 与 public verifier exact horse set 聚合为唯一 `AUDITED_COMPLETE`；真实全量运行仍待前序批次完成
- [x] (operations) 实现 complete execution + 六类 exact child 自动生成 global approval binding artifact；aggregate 首选 root+manifest SHA 严格重载，取消正常流程人工 JSONL 接线
- [x] (operations) 实现 proposal prefix→identity/module 人工 review→双 approval→automatic binding 的零写审批前沿；后续批次等待时可流水线 review，但不自动批准
- [x] (integration) 将 identity proposal rows 按 verified provider ID、official/local crosswalk、strong biodata、observed ID、create-new 跨语言防重、ambiguous/blocked 分 cohort；全部保持人工审核
- [x] (application) module approval 发布前逐行重放 exact candidate、重建 review rows 与 deterministic manifest；rehashed 摘要失败关闭
- [x] (application) module candidate/proposal/approval JSON/JSONL 拒绝 duplicate keys 与非有限常量
- [x] (application) identity candidate/proposal/reviewer decisions/approval JSON/JSONL 同步拒绝非有限常量
- [x] (integration) targeted materializer 与 External staging 全部内容寻址输入统一拒绝 duplicate keys 与非有限常量
- [x] (integration) TRA HTTP 成功响应（含 credential diagnostic）、OpenAPI fingerprint 与 targeted seed 在 cache/artifact 前统一严格 JSON
- [x] (integration) bulk target manifest/JSONL 与 targeted batch seed/definition/checkpoint 输入统一严格 JSON，重算 SHA/marker 不得绕过
- [x] (operations) 回归 strict ingress、完整 research 与 Django 审批/staging 链，并记录 event 956 生产暂停边界
- [ ] (operations) 验证四地区、年份、grade、discipline target 守恒
- [ ] (integration) 验证 race/participant/provider horse/identity/gap 守恒
- [ ] (application) 验证 profile 字段、二代血统、完整生涯、统计和主胜鞍
- [ ] (operations) 验证全量 artifact 重放零写、无自动发布/QQ/邮件/race-live 副作用
- [x] (operations) 更新 current_state、decisions、project_overview、project_status
- [ ] (operations) 输出最终覆盖报告、剩余 provider/source gap 和可复现命令清单

## 9. 2026-09-01 续跑增量

- [x] (operations) 在 latest main 干净 worktree 迁移依赖闭包，保留历史 dirty worktree 与主工作区不变
- [x] (integration) 重建 execution as-of=2026-09-01 的 calendar/source/bulk readiness；12,048 target、11,939 due、
  10,795 bulk、1,144 pre-2005、109 not_due 均与冻结分母守恒
- [x] (integration) 将 bulk 分区从年度范围修正为单地区单自然日；生成 31,656 个分区、88 个 region-year 批次
- [x] (integration) 新增官方 OpenAPI deterministic capture/review artifact 与 schema-drift 回归测试
- [x] (operations) 完成两轮 Full 工程复审，关闭 OpenAPI 漂移、年度范围分区和变更包缺 proposal 三项 finding
- [ ] (operations) 合并并发布当前 runtime 后，从 France 2005 ordinal 1 开始按账本持续执行 88 个 bulk 批次
- [ ] (integration) 执行 65 个 pre-2005 targeted 批次，与 bulk stable ledgers 合并并完成全部 zero-search enrichment
- [ ] (application) 完成全部 identity/module 审核、External/canonical apply、public verifier 与 final global audit
