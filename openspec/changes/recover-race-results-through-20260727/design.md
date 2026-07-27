## Context

生产只读盘点以 `2026-07-27`、生产 `HEAD=a59956b327157d29630fab1f1c98ba9c9cacfed0` 为准：

- `2026-07-08` 至 `2026-07-27` 有 59 条公开 `RaceEvent`，精确分解为 `40` 条真实缺失赛事的零结果行、`9` 条重复产品零结果行、与其配对的 `9` 条已有确认结果历史行，以及 event `924` 的 `1` 条 provisional 行；因此真实赛事分母为 `40 + 9 + 1 = 50`。
- 9 场重复赛事存在两套不同 `RaceSeries`/`RaceEvent` 身份；具体 event 对照与 40 场全集冻结在 `source_research_20260727.md`。
- 9 条历史总账实体已有全部 `is_confirmed=true` 的结果，但 `result_confirmed_at` 为空，前台重点赛事继续读取另一条无结果的公开赛程实体。
- event `924` 有 7 条 TRA 结果但均未确认；其余待处理赛事没有结果。
- 重点赛事口径内有 26 条已过期公开赛事仍为 `scheduled + results=0`。
- 公网页面的“已完赛”筛选实际只展示到 `2026-07-05`，而 7 月 9–26 日多场已举办赛事仍显示“赛前”。

现有能力包括：五地区候选 adapter、`RaceEventDataCandidate`、赛事详情编排、历史总账、赛事生命周期、准实时 revision/authority 模型、人工官方证据命令和生产备份/回滚规范。当前缺少的是把这些能力组合成一次“固定窗口、逐场守恒、结果专用”的恢复流程。

## Goals / Non-Goals

**Goals:**

- 对冻结窗口中的每条公开赛事和每个真实赛事身份给出可审计终态。
- 将候选收集、官方确认、身份审批和生产 apply 分开。
- 复用现有 adapter 与数据模型，只新增 canonical 产品映射所需的一份模型迁移；不新增恢复 run、receipt 或 rollback 数据表。
- 对重复实体采取保守投影：保留记录，不按模糊名称自动合并或删除。
- 在原子写入、独立 verifier 和浏览器验收后，使已到期公开赛事不再错误显示“赛前”。

**Non-Goals:**

- 不启用全量准实时 scheduler、TRA 公开灰度或自动官方提升。
- 不补抓窗口外历史赛事、未来赛事、赔率、血统、新闻或 QQ 推送。
- 不重构五地区 adapter，不创建新的通用主数据合并框架。
- 不因本次修复删除 `RaceEvent`、`RaceSeries`、历史目标或既有赛果。
- 不把“候选已抓到”“第三方两源一致”解释为官方确认。

## Decisions

### 1. 以双层清单表达 59 条记录与真实赛事身份

inventory 同时保存：

- `event_rows`：冻结的每条生产 `RaceEvent` 身份、详情计数和前台产品属性；
- `race_groups`：经规则发现但尚未批准的真实赛事分组；
- `identity_reviews`：逐组批准或 blocker。

自动分组只产生候选，不产生写入权限。最终 canonical product event 必须由精确 `RaceSeries/year/region/date` 证据或人工批准指定。选择这一方案，是因为当前 9 组重复实体跨不同 `RaceSeries`，现有 reconciliation 的“同系列同年度唯一匹配”不能安全自动解决。

替代方案是直接按中文名和日期复制赛果；该方案会把冠名变化、同名赛事和错误日历日期放大为生产污染，因此拒绝。

到期判定不另写日期猜测：inventory 使用 `race_event_lifecycle.decide_race_lifecycle()` 的同一纯函数和地区时区契约。存在 `race_datetime` 时以 `T+30m` 为到期边界；缺少时间时以赛事当地次日零时为边界；缺少/非法时区或日期时直接形成 blocker。inventory 时已经持久化且身份未漂移的 `cancelled/postponed` 沿用终态语义，不进入赛果应到分母；当前 route registry 没有通用取消/延期 marker contract，本批若人工发现新的取消或延期事实只能形成 blocker，扩充官方 outcome contract 另立 change。

### 2. 扩展既有编排为结果专用 recovery purpose

在现有 `orchestrate_race_event_crawl` 之上增加受限的 `race_result_recovery` purpose：

- 仅接受冻结 event ID 和 `modules=["results"]`；
- 不要求同时抓取 `runners/history_winners`；
- adapter 即使返回其他模块，aggregate 也只保留结果模块；
- 每个 adapter 输入必须由已批准 inventory 生成；
- 请求预算、source cache、resume、coverage、candidate SHA 和 apply-check 继续复用现有门禁；
- candidate 网络访问必须先通过既有 source permission/runner allowlist；`manual_browser_only` 官方路由不得被该 purpose 自动请求或借助普通 HTTP 绕过。

选择扩展既有编排而非新写一套 downloader，是为了保留已有请求预算、来源等级、原子 artifact 和恢复语义。

### 3. 候选来源与官方确认分层

候选层可使用：

- 日本：JRA/NAR adapter；
- 中国香港：HKJC adapter；
- 英国：Sporting Life；
- 法国：ZEturf；
- 美国：TOBA 已发布的精确 Equibase chart discovery；TOBA 尚未更新的 7 场先用
  Sporting Life 日期结果页生成候选，再由 Equibase 按赛场/日期人工确认。Equibase
  `manual_browser_only` chart 只产生结构化人工 receipt；本批禁止自动下载 chart，也不把
  既有离线 PDF parser 解释为网络许可；
- TRA：只作为既有 provisional 观察或补充比对。

`scheduled` 是本次已到期 recovery inventory 的合法冻结状态。runner 仅在
`purpose=race_result_recovery` 时向 JRA、NAR、Sporting Life 和 ZEturf 详情 adapter 传入
显式 recovery mode；普通历史详情模式继续只接受 `finished`。来源仅给前若干名并把其余完赛马
标为 `Also Ran/N/A` 时，adapter 保留已知事实但写入 `result_order_complete=false`，coverage
必须产生 `incomplete_result_order` blocker，禁止按页面排列补造名次。
聚合层对所有恢复来源再次独立核对：candidate 必须携带冻结 `event_id`，参赛名单中除
`withdrawn/scratched` 外的每匹马都必须恰好进入结果，内部 `finish_position` 必须为从 1
开始的连续唯一序列。缺参赛名单、缺马、重复身份、无效名次和 TOBA discovery-only winner
一律标记 `result_order_complete=false`，不能因 adapter 命令成功而放行。
UK 与 US Sporting Life 虽复用同一 parser，但在单次 run 中使用互不相同的
candidate/review/summary 标准路径。coverage 只读取并验证当前 state 记录的标准 combined
artifact identity，拒绝 `--candidate-jsonl` 替换；随后逐场比较聚合层强制写入的
`source_provider/racing_region` 与冻结 target，防止自报 metadata 或跨来源 event ID 绕过。

本批 HRN `/entries-results/YYYY-MM-DD` 实测重定向至首页，不能承担结果恢复。其 adapter
只保留既有行为回归，不进入本批 source map。逐场来源和当前可用性冻结在
`source_research_20260727.md`。

官方确认层只接受当前已批准的人工官方路由：

- JRA `/JRADB/`
- NAR `/KeibaWeb/TodayRaceInfo/`
- HKJC `/racing/information/`
- BHA `/racing/results/`
- France Galop `/en/racing/`
- Equibase `/static/chart/`

官方 evidence 只保存允许的结构化事实、URL、marker、观察时间、reviewer、route contract digest 和事实内容 SHA；不保存受限原始页面或凭据。candidate 自动化许可与 official promotion 权限是两套独立门禁，任一缺失都 fail closed。第三方一致可以降低人工比对成本，但不能单独令 `is_confirmed=true`。

现有 `race_live_manual_official_evidence` receipt 绑定 live allowlist、official incident 和
provisional revision，且 participant schema 不允许同着或非完赛，因此只能继续服务 event
`924`。其他 non-live 目标新增 recovery 专用离线 receipt validator：它复用 route registry
的 host/path/marker/digest 校验，但独立支持 repeated/null official position、稳定
`internal_order`、非完赛 status 与字段级 provenance；不得伪造 live allowlist、tracking、
incident 或 publication authorization。

### 4. 重复实体使用“批准投影”，不做删除或隐式合并

对 9 组已有赛果的重复实体：

1. 重新核对官方结果，不直接信任旧 `is_confirmed=true`；
2. 审批 canonical product event；
3. 将结果以新 evidence 身份投影到 canonical event；
4. 非 canonical event 保留原数据，并通过显式产品展示选择避免同一真实赛事重复出现；
5. 不改历史目标所有权，除非另一个已批准 reconciliation change 明确授权。

投影前逐字段比较名次、马号、马名、骑师、时间、margin 和非完赛状态；冲突时整场阻断。

已批准的展示选择持久化到新增 `RaceEventProductCanonicalLink`：

- `duplicate_event` 与 `canonical_event` 均为 `ForeignKey(PROTECT)`；数据库用条件
  `UniqueConstraint(duplicate_event, condition=is_active)` 保证每个 duplicate 至多一条 active
  选择，同时允许回滚后创建新审批行并永久保留 inactive 历史；
- 数据库 `CheckConstraint` 拒绝两端相同，`identity_sha256/manifest_sha256` 为非空 64 位
  digest，并为 `(canonical_event, is_active)` 建索引；跨 FK 的同地区/同年度条件不能伪装成
  数据库约束，必须由事务服务层校验；
- identity approval 使用 PostgreSQL transaction advisory lock，并按 event ID 锁定两端与
  相关 active link；SQLite 走同一确定性校验但不宣称等价并发安全。服务层拒绝跨地区/年度、
  自环、链式 canonical 和环；
- 保存 `identity_sha256`、`manifest_sha256`、`approved_by/at`、`is_active`；
- 日历查询排除 active duplicate，直接访问旧详情 URL 仍可读取，并显示 canonical 赛事链接；
- 回滚将本次 link 置为 inactive，不删除赛事或审批审计；改选 canonical 必须创建新的审批
  link，禁止覆写旧 inactive 行。

选择显式模型而不是根据名称在查询期临时去重，是为了让展示身份可审计、可回滚且不随文案变化。

### 5. 所有正式赛果写入必须经过 projection arbitration

恢复流程不得直接把 `RaceEventResult` 当作唯一写入口。每场先锁定 `RaceEventProjectionControl` 并按 owner 分流：

- `live`：仅当既有 allowlist、incident、provisional revision、tracking 与 official
  authorization 全部满足时复用现有 manual official evidence/publication transition；event
  `924` 必须走此分支。任一 live prerequisite 缺失都 blocker，禁止抢占 owner 或调用 recovery
  direct projection。
- `historical`：当前仓库没有可直接复用的 historical official revision 投影原语；新增
  recovery projection service，复用 strict canonical hash、observation/revision/evidence
  模型与 legacy projection 字段映射，但不调用要求 `LIVE + tracking claim` 的
  `apply_race_result_observation_revision()`。
- `unmanaged`：以 CAS 将 owner 晋级为 `historical`、generation `+1` 并绑定本次 manifest，
  随后走同一 recovery projection service。
- `manual_paused`、owner/generation/manifest 漂移或已有 current revision 冲突：整场 blocker。

non-live receipt 在创建 revision 前必须将每条赛果精确绑定
`RaceEventParticipant + RaceEventParticipantSourceIdentity`。优先采用受审 source runner ID；
缺少 ID 时使用 manifest 绑定的官方原名、马号和来源 URL 创建 recovery stable key，任何同名/
马号冲突、已有 participant 漂移或模糊匹配都整场 blocker。不得用中文译名或相似度创建身份。

官方结果先形成 immutable `RaceResultObservation`、
`RaceEventRevision(phase=official)` 及逐 participant item/evidence link，再由 recovery
projection service 替换当前 projection。`RaceEventResult.finish_position` 继续作为唯一内部
顺序，`official_finish_position` 表达官方并列名次；非完赛项使用稳定内部顺序与
`running_status`。替换允许精确批准的 result-row create/update/delete，但不得删除
`RaceEvent`、`RaceSeries`、历史目标或 revision/evidence。

替代方案是恢复命令直接 `update_or_create(event, finish_position)`；该方案会绕过 current revision、last-known-good、owner generation 和官方 publication contract，因此拒绝。

### 6. 一场赛事一个事务，整批使用冻结 manifest 守恒

apply 以冻结 manifest 和独立 approval 双 SHA 为入口：

- 每场事务内锁定 event、projection control、current revision、participants 和现有 results；
- 重算 before identity；
- 创建 official observation/revision/evidence 并通过对应 owner 分支替换结果，再设置 `status=finished`、`data_quality_status` 和 `result_confirmed_at`；
- 写 `OperationLog` 与 rollback ledger；
- 任一赛事失败只回滚该场，但整批 summary 明确标记不完整，不能宣称窗口闭环。

逐场事务便于隔离单个来源 blocker；批次 accounted 报告确保每个 target 都进入 confirmed/cancelled/postponed/blocked 之一，但只有 `blocked=0` 且所有应到赛事为 confirmed 时，run 才能标记 `completed`。

rollback ledger 复用既有安全 artifact 模式，每场使用独立、不可覆盖的 write-ahead 文件：
预占路径后在事务内锁定并形成完整 before/after identity，提交前以 `0600 + fsync + atomic
rename` 发布；若事务提交失败则清理本进程拥有的 ledger。崩溃留下的孤立 ledger 必须由
verifier 识别为 `prepared_not_applied`，不能用于 rollback。成功回滚仍保留本次
revision/evidence/OperationLog，并另写 rollback 审计；回滚同样经 owner/generation 与
revision identity 校验，将 current pointer 和投影恢复到 last-known-good/写前 revision。

恢复 management command 必须显式加入 `historical_batch_runner` 的 read/write command
allowlist 与 phase/argument 分类；crawl 仍为 `network=true/write=false`，apply 为
`network=false/write=true`，verify 为双 false，任何命令不得同时触网和写数据库。

### 7. 生命周期与前台只消费明确终态

恢复 apply 后：

- 有官方确认完整赛果的赛事为 `finished`；
- inventory 时已存在且未漂移的取消或延期赛事分别保持 `cancelled/postponed`；新发现的取消/延期因缺 route contract 保持 blocker；
- blocker 不伪造 `finished`，但必须在恢复总账中可见；
- “已完赛”筛选继续按 `status=finished`，冠军继续要求确认结果；
- 同一 approved race group 只展示 canonical product event。

不通过页面层按日期猜测赛事已结束；状态变化只能来自已批准的恢复 evidence 或现有生命周期正式路径。

## Risks / Trade-offs

- [官方页面只能人工访问，50 场核验工作量较大] → 先用 adapter 生成结构化候选和逐场 deep link，再由人工官方路由核对关键事实；允许分地区批次，但不缩减总分母。
- [9 组重复身份可能并非同一赛事] → 自动规则只提出候选，跨 `RaceSeries` 必须人工批准；冲突保持 blocker。
- [旧赛果虽标记 confirmed 但缺 `result_confirmed_at`] → 一律重新绑定本次官方 evidence，不继承旧确认语义。
- [第三方与官方结果字段粒度不同] → 以官方 finish order/status 为准；缺失的 margin/time 可为空，不能用第三方值覆盖官方冲突。
- [route registry 或 BHA 专用 contract 在执行前过期/漂移] → receipt、dry-run 与 apply
  均重读受审文件并核对 registry/contract/terms digest 与 `valid_until`；旧 receipt 整场拒绝。
- [同场逐场事务可能造成部分成功] → verifier 与批次状态必须明确 `partial`，未闭环时不宣称完成；rollback 可按 ledger 精确回退已应用场次。
- [恢复写入与 live/historical owner 冲突] → 所有写入先锁 projection control 并按 owner 分流；event 924 只走 live official transition，禁止 direct projection。
- [前台去重可能隐藏错误 canonical event] → canonical 选择纳入审批与浏览器逐场抽检，且不删除底层数据，便于回滚。
- [生产期间自然任务造成漂移] → apply 前暂停 beat，排空相关队列并锁定 before identity；新闻链路仅在最短必要窗口暂停。
- [历史赛事缺少 live participant identity] → recovery receipt 先做 exact participant
  binding；缺失 source runner ID、重名/马号冲突或既有身份漂移整场 blocker。
- [manual receipt 无法表达同着/非完赛] → non-live 使用 recovery 专用 schema；event 924
  继续使用既有 live schema且以本场实际唯一名次为前提。
- [文件 ledger 与数据库不是同一事务资源] → 每场 write-ahead ledger、owner inode 校验、
  fsync/atomic rename、提交异常清理与 orphan verifier；不使用共享 append 文件。

## Performance / Observability

- inventory 对 59 行使用批量 `select_related/prefetch`，自动化测试硬门禁 `<=25 SQL`；
  公开 40 场日历继续满足既有 `<=12 SQL`，canonical link 必须批量加载，不得逐 event resolver。
- candidate prepare 总请求 `<=75`、单请求 timeout `<=30s`、source cache `<=512 MiB`；
  cache/resume 命中不得重复传输，预算耗尽转逐 event blocker。
- apply 最多 50 个 race group、按地区串行、一场一事务；不在 Celery 普通新闻队列执行，
  通过 historical runner 的独立 phase/lease/checkpoint 暴露进度。
- 每场 prepare、receipt、apply、rollback 与 verifier 均输出稳定 reason code；网络失败、
  route 过期、身份冲突、owner 漂移、ledger orphan 和页面验收失败不得静默，只能进入
  machine-readable blocker、HistoricalBatchRunEvent 或 OperationLog。

## Migration Plan

1. 在独立 worktree 完成测试先行实现、focused/完整回归、Django check、迁移漂移和独立代码审核。
2. 取得精确 release 授权后部署代码，保持所有恢复/网络/自动 apply 开关关闭。
3. 在生产生成只读 inventory，使用共享 lifecycle predicate 审核 59 条 event rows、race groups、重点 26 条缺口和 source route。
4. 取得 inventory SHA 的网络 prepare 授权后，只对具备自动化许可的 candidate route 按地区
   生成候选；官方 `manual_browser_only` route 由人工浏览器产生结构化 receipt，不写业务表。
5. 完成人工官方核验与重复身份审批，生成字段 diff、coverage 和 dry-run。
6. 针对精确 candidate/approval SHA、预计 create/update/delete 数、canonical 映射和 blocker 取得生产写入授权。
7. 暂停 beat、排空相关任务、创建并校验 PostgreSQL custom-format 备份与环境备份。
8. 分地区串行 apply；每批立即运行 owner/revision-aware 独立 verifier 和幂等重放。
9. 验收 `/races/?when=finished`、全部/重点、五地区、目标详情页、移动端和桌面端；确认新闻/QQ 未触发。
10. 恢复调度，观察错误日志与页面健康；回写规定文档。

回滚优先使用逐场 rollback ledger；若 ledger verifier 失败或出现跨表异常，停止业务写入并使用写前数据库恢复点。

## Open Questions

- 最终 inventory 是否仍精确满足 59 条公开记录、50 个 race group 与本 change 的 event ID
  全集；任何漂移必须 blocker、重新报告并重新审批，不能在执行时调整分母。
- 9 组重复实体的 canonical product event 由现有重点赛程行还是历史总账行承担，需以逐组审核包决定，不能预设。
- 个别官方页面若只给冠军而不给完整 finish order，只能计入 accounted blocker；默认不接受整场 complete，且最终 run 不能标记 completed。
