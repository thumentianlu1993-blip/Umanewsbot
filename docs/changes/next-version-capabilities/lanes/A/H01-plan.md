# A-005 / H01 目标集与分母方案（待独立审核）

状态：方案阶段，未执行目标生成、生产取数、补齐或公开。DDL：2026-10-06 18:00 Asia/Shanghai。
代码阅读基线 `815b3181fa61e7fbbff714c7d7326e5598dc71a6`；F01 业务合同受审 SHA `0e05029c1ed00713a6f66e461e6753c1e4dadb27`。这不是 main 已交付证明。A-004 v4/v5 审核包保持不可变，F03 缺口保留，不通过改写 F03 状态解锁 H01。

本卡只负责近三年全参赛马目标集、2020 年以来一级赛全名单名称目标和本线报告。先形成可审核的只读 loader/纯目标规划方案；不另造 writer、修改共享模型、F01、发布合同或其他线文件。本轮明确授权覆盖方案，本卡不执行生产查询；后续交付遵循根 AGENTS.md。

## 范围与固定时间

- 近期目标：已有九地区赛事及已准入来源能枚举的参与者，初始以赛事赛地 `local_date` 落在 **2023-10-03..2026-10-03，含两端**，并有实际出赛证据为核心近期分母。不是出生日期/马龄窗口，不只取 G1 或已建档对象。
- 名称目标：2020-01-01..冻结日的全部一级赛名单，含 Jpn1、香港本土 G1，不能缩成胜马、前三名或只保留近期集合。名单内退赛者仍保留并标未出赛，与近期“实际出赛”口径分开。
- 一级赛类别：G1、JPN1、香港本土 G1 已有范围明确；日本 JG1/国际障碍一级是否同属本卡名称集合，交协调者在方案冻结时明确为配置，当前不静默纳入或排除。旧 P0 的 G2/G3/JG2/JG3/JPN2/JPN3 不由复用函数带入本卡历史集合。香港本土 G1 要受审等级证据/地区，不能靠赛名包含“杯”或 LOCAL_GRADE 自动认定。
- 参数沿受审 F01：未来参赛优先 30 天、近期新闻 90 天；不沿旧 P0 队列的新闻 30 天默认值。未来日期建议 `[as_of+1, as_of+30]`；当日计划参赛单列当日队列，不伪造“未来已出赛”。当前赛季使用有证据的地区赛季配置；跨年赛季不会改变参赛的 local_date 归属。
- `as_of_date`、`snapshot_at_utc`、地区时区/赛季版本、窗口配置、来源政策 SHA、代码 SHA、输入 schema/hash 必须固定。初次窗口不因 10/06 运行时间改变；上线滚动按三年日历区间（闰年明确规则）产生新 snapshot，旧分母不可回写。

## 当前代码与复用边界

| 入口 | 当前可复用点 | 不足或禁止当作完成证明 |
|---|---|---|
| `p0_horse_profiles._participant_identity_keys` | provider namespace + horse ID/URL 的候选稳定键抽取 | 候选键不等于 verified；runner ID 是赛事内参赛项键，不等于跨场 horse ID |
| `_event_participants` | runner/result 结合及号码/身份冲突的保留信息 | 不读取 versioned participant/revision 的完整生效语义；同名回退只能召回，不能跨地区自动合马 |
| `_identity_index` | profile 已留存身份键索引 | 从全 HorseProfile 出发且 source_refs 为候选；未建档对象会遗漏，不能直接调用全表索引作有界生产读取 |
| `_major_race_events` | 已有地区/等级筛选 | P0主范围五地区；候选扩展仍缺独立爱尔兰，且major集合不是近三年所有参赛集合 |
| `build_p0_completion_queue` | 最新race_date、候选注意事项、新闻关联等优先因素 | 只从已建档且P0 source active出发；旧新闻30天，不可作为本卡完整分母 |
| `horse_profile_completion.plan_profile_completion` | 本地 ExternalHorse 匹配和补全分层说明 | 只遍历已建档profile，部分匹配走名称；H01身份去重不能复用为自动授权 |
| `horse_profile_publish.evaluate_basic_publish_gate` | BASIC门槛、hidden/locked阻断 | 门槛eligible不等于已公开；H01只读计量，不调用auto_publish/commit |
| `horse_race_records.resolve_existing_race_record` | 强来源/规范赛事/历史歧义识别原则 | 已建档档案内比赛去重不等于跨地区马匹去重；upsert和补全apply不在本卡 |

## 数据流与账本

从现有赛事/已准入留存名单开始，而不是从 HorseProfile 开始：赛事范围 → 生效参与项版本 → 实际出赛/仅报名/未知分类 → 强身份映射及冲突保留 → 近期与历史集合归属 → 优先标签 → 缓存/staging/profile/public 分层计数 → 冻结输入与可复算目标账本。产物只读，后续补齐/名称采纳/公开继续复用既有受审链路。

1. **赛事全集与缺口**：逐地区列 existing canonical 赛事及已准入来源可枚举赛事，保留未有identity/binding、缺名单、缺日期、重复届次待核的事件。不能只选择“结果已确认”或已公开成功赛事。source与canonical映射不明保留独立来源赛事及待核关系，不让同名赛事串联。缺整场名单且人数未知时记录 `unknown_participant_count_events`，不能伪造一个马匹占位或给虚假精确总分母。
2. **生效版本**：有projection control时以固定snapshot的current racecard/result revision指针与publication/provenance为起点；同时保留未发布候选的潜在目标池。指针缺失/冲突不取任意max revision，也不把last-known-good自动当现行。明确 supersedes与更正链；legacy runners/results仅在无有效versioned输入时补充，跨表示层去重需事件+参赛项证据。两个表示不一致保留冲突，不能重算为两匹或自动删除旧身份。
3. **实际出赛**：可信结果终态、明确source start证据或 `HorseRaceRecord.start_status=started` 且exact date/provenance可支持近期；退赛/取消/未出赛不当近期实际出赛。running/declared、是否出赛不明、缺可信时间留待核池并记数；fell/PU/DNF/DQ等实际出赛按明确源语义纳入，refused等歧义不凭枚举猜测。补充的HorseRaceRecord须限于已有九地区及已准入可枚举来源，不悄悄扩大履历来源范围。
4. **身份与去重**：唯一 verified HorseExternalIdentity（source/namespace/external_id）及其profile映射作为强锚点；同profile多个已核验源键归一。身份 observed/rejected/retired、namespace缺失、一个源键连多profile等保持未解/冲突，不用同名、译名、父母+出生年直接自动合并。`horse_identity_verified_keys` 旧receipt需核证据与撤销；source_refs普通候选键只召回。赛事内number/external_runner_id不能全局去重。
5. **未建档**：有稳定horse源键但未映profile形成 `unresolved_source_target`；无稳定horse键时使用固定参与项来源引用（event/representation/row/ref），而非name hash伪造马匹ID。同一马的已核验多源挂接去重一次；未解别名不猜去重，分别列“原始项/已解析唯一马/未解目标/冲突组”，不能把四者直接相加冒充真马数。
6. **集合与优先**：近期实际出赛集合、历史一级名单名称集合独立保留membership；交集只去重执行队列，不丢任何归属。非核心未来参赛/新闻对象进入增量或优先补充池，不灌进已经发生近期参赛分母。默认排序元组为当日/未来30天、当前赛季、近期新闻90天、最近实际出赛日期降序、已有未完成模块与稳定target key；逐项reason、源引用和配置可解释，不按马龄或一国总样本吞掉历史处理配额。具体三类标签重叠与排序优先级为工程建议，送原R/协调者冻结后实施。
7. **分层计数**：cache evidence present/unknown、ExternalHorse staging matched/unmatched/ambiguous、HorseProfile exists/no_profile、public actually_visible/hidden/unpublished/blocked/unknown分别记量。cache不是staging，staging不是建档，门槛eligible不是public；层可以重叠但不能相加当总目标。公开判定复用现有实际可见性规则并受publication状态/hidden/锁约束，保留来源更新时间与生涯partial/null/0的差异。
8. **冻结与新增**：固定同一数据库只读snapshot的规范化输入加已存源manifest；排序/去重输出canonical JSON摘要。重放同输入必须得到同targets/membership/counts。snapshot后新增事件、参赛项、新闻或更正进入独立delta账本，按新snapshot重算并记录added/removed/reclassified及理由；不能只存updated_at高水位就承诺可重现历史内容。只读预算截断时产物为partial，禁止发布“冻结完整分母”。

## 最小产物与实施切片

拟新增纯planner与只读loader（实现阶段再定文件）：规范化ParticipationInput、IdentityEvidence、TargetSnapshot、TargetMembership、PriorityEntry和CoverageGap，沿F01显式时间/hash/版本语义，保持其公开字段边界。不是新F01 DTO或writer。优先复用现有身份键抽取/记录解析逻辑，补versioned参与项与未建档枚举；无法安全直接复用的全表查询只复用语义，不调用带副作用/无界方法。

目标产物包含参数、schema和policy SHA、输入完整性、窗口/地区分母、raw项数、verified unique数、unresolved source targets、conflict groups、未知人数事件、两集合membership/交集、优先原因、分层处理面、增量和缺口。F06先做有界容量取数，方案见 H01-readonly-count-plan.md；未知数量/权限继续unknown，不使用旧4027试点统计作为本版分母。

实施顺序为本地最小RED → 纯planner GREEN → 固定输入复算/并发边界 → 原R code review；真实取数由root按有界只读方案安排，不能靠本地mock宣布真实分母。当前仅文档，没有生产SQL、队列恢复、网络调用或模型迁移。

## 待协调与验收边界

方案审核需冻结：历史JG1归属、地区赛季证据、优先元组、legacy/更正输入取舍与读预算。主线/生产schema迁移一致性、canonical映射、全部来源manifest、当前许可、真实row数/耗时/索引均unknown，先交root/R核验。F0335个文件的后续归因独立保留；H01不能通过缩短窗口、只取已建档或胜马绕开缺资料。

完工要求：两个目标集及优先账本可复算，未建档/未解/缺来源保留，分层计数不混称公开，真实完整输入与遗漏账本能守恒；未取得全输入则明确部分完成。本方案尚未生成真实目标数量或证明10/30吞吐可行。
