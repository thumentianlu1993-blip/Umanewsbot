## Context

`horse-profile-page-mvp` 已在生产上线，并已发布两匹样本马验证完整前台链路。现有 `generate_horse_profiles` 只从 active 且 `target_zh` 非空的 horse `TermEntry` 生成草稿，上一轮 `complete_horse_profiles --dry-run` 覆盖 `21596` 匹马但完整二代血统为 `0`，主要原因是本地外部缓存没有命中或地区来源不可用。

经过本轮需求澄清，P0 马不再只等于“已有中文译名的正式马名术语”。新版 P0 马由两部分组成：

- 当前范围：active horse `TermEntry` 中已有中文译名的马。
- 重点赛事参赛马：日本、中国香港、英国、法国、美国所有 `G1/G2/G3/J-G1/J-G2/J-G3/JpnⅠ/JpnⅡ/JpnⅢ` 赛事的参赛马，覆盖历史与未来全部已知赛事。

因此本变更同时处理 P0 范围同步、无中文译名术语、资料补全、人工审核和未来自动化预留。公开页面、新闻详情、首页和关注流仍不得实时请求第三方来源。

## Goals / Non-Goals

**Goals:**

- 建立可重复计算的新版 P0 范围：从正式术语和重点赛事参赛证据生成或更新 `HorseProfile`。
- 支持暂无中文译名的 active horse term，翻译命中时保留原文，不参与中文替换。
- 建立 P0 来源结构化记录，保留 `term_active_with_zh`、`major_race_participant`、赛事、等级、地区和 source URL。
- 建立持续同步机制，让未来重点赛事出赛/赛果进入系统后自动刷新 P0 范围并触发补全队列。
- 建立五地区补全队列和 adapter 能力，首批完成每地区 10 匹新版 P0 马的完整资料补全。
- 定义完整资料状态：基础事实字段、二代血统、完整赛事履历、主胜鞍、来源 URL 和人工审核记录全部满足后才计入完整样本。
- 支持按模块审核基础资料、血统、赛事履历和主胜鞍，并让 commit 幂等写入 `HorseProfile` / `HorseRaceRecord`。
- 首批每地区人工发布 1-2 匹完整资料马做公开验收；其余可停留在 `ready`。
- 预留自动化路径：已发布马可更早自动增量更新，未发布马自动首次公开另行灰度。

**Non-Goals:**

- 不让普通用户请求路径触发 netkeiba、HKJC、Sporting Life、Racing Post、France Galop、Geny、HRN、Equibase 等外部请求。
- 不在本阶段实现未发布马的自动首次公开；首发仍由人工发布。
- 不把 Listed、Open、地方重赏 `LOCAL_GRADE` 纳入本次 P0 重点赛事定义。
- 不要求 `intro` 作为完整资料硬门槛；它是编辑内容，可以后续生成或人工维护。
- 不在本轮建设注册用户、复杂通知、深层血统图谱或全量 SEO slug。
- 不把 `new-village/KeibaScraper` 设为默认强依赖，除非样本评估证明其稳定性、字段覆盖和合规风险可接受。

## Decisions

### 1. 用结构化 P0 来源取代隐含定义

新增 `HorseP0Source` 或等价结构保存 P0 身份来源。`term_active_with_zh` 来源记录绑定 horse term；`major_race_participant` 来源记录绑定重点赛事、等级、地区、参赛/赛果证据、source URL 和审核状态。P0 身份采用追加式审计：如果上游数据纠错，不直接删除历史，而是标记来源 inactive/revoked。

备选方案是继续从 `HorseProfile.source_refs` 或 `TermEntry.notes` 推断 P0。它实现快，但无法稳定统计覆盖率、追踪来源撤销，也难以驱动持续同步。

### 2. 升级术语库以支持“暂无中文译名”

`TermEntry.target_zh` 应允许为空，并新增 `translation_status` 或等价状态区分 `pending` 与 `translated`。`is_active=True` 表示可信实体可被识别，不再等同于“可用于中文替换”。翻译、改写、术语应用和校验需要基于 `target_zh` / `translation_status` 判断：

- 有中文译名：进入术语表并可替换为中文译名。
- 暂无中文译名：进入马名保护名单，最终译文必须保留原文，不做中文替换。

备选方案是给 `target_zh` 填占位值。占位值容易污染前台、CSV、翻译替换和 tag 展示，因此不采用。

### 3. P0 范围同步以重点赛事证据为准

重点赛事参赛马必须能追溯到某个五大地区重点赛事及其出赛/赛果证据。优先使用系统内结构化 `RaceEvent`、`RaceEventResult`、外部缓存和导入 artifact；当数据缺口存在时，补全流程可以受控补抓赛事参赛名单，但必须先落成可审核 artifact。不能因为外部马名搜索命中就直接认定为 P0。

备选方案是按外部马资料搜索结果扩容 P0。它会把 P0 扩成“所有能搜到资料的马”，失去重点赛事边界。

在正式同步写入前，系统先提供只读候选提取层。它从符合等级的 `RaceEventRunner` / `RaceEventResult` 合并同场观察，输出完整观察 JSONL、候选池 JSON、每地区 10 匹审核 CSV、summary 和逐文件 SHA-256 manifest。跨赛事只允许使用既有 profile、来源内 external horse ID 或完整“多语种马名 + 父名 + 母名 + 出生年份”归并；共享任一强身份键的观察按连通关系聚合，后续血统会回填，连接多个既有 profile 或出现矛盾血统时转人工冲突。只有马名的观察保持独立并标记 `needs_identity_enrichment`；样本只抑制弱身份同名重复，不排除不同强身份的同名马。这一阶段不创建术语、`HorseProfile`、`HorseP0Source` 或身份冲突记录。

### 4. 首批验收是五地区各 10 匹完整资料样本

首批验收对象是从新版 P0 范围中，日本、中国香港、英国、法国、美国各 10 匹完整资料马，共 50 匹。样本优先级按近期站内新闻相关度、术语优先级、重点赛事证据、外部匹配信号和人工标记排序。若某地区某个样本无法补齐完整资料，不能降级通过；可保留失败证据并换同地区替补，直到补足 10 匹或明确地区 blocker。

备选方案是固定抽样，无论成功失败都算批次完成。它无法满足“每批都要求补足完整内容”的目标。

### 5. 完整资料状态高于现有 `complete_pedigree_2gen`

现有 `complete_pedigree_2gen` 只代表二代血统完整，不等于本专项完整资料。新增 `complete_profile_full` 或等价状态，硬门槛包括：

- 身份和 P0 来源证据。
- 中文名可为空，但必须有可展示外文原名和地区。
- 国家/地区、性别、毛色、出生日期、马主、练马师、生产牧场。
- 父、母、父父、父母、母父、母母。
- 来源可获得范围内完整赛事履历；退役马覆盖完整生涯，在役马覆盖到最近同步时间。
- 赛事履历保留退赛、取消出走、未完赛、失格等状态。
- 赛马生涯状态或等价同步标记，用于区分退役马的完整生涯履历与在役马截至最近同步时间的完整已知履历。
- 主胜鞍沿用既有定义：从胜利 `HorseRaceRecord` 中按最高等级计算，同等级多场全部展示，并允许人工 `is_major_win` 覆盖。
- 来源 URL、人工审核人、审核时间和模块批准记录。

`intro`、相关新闻和站内相关赛事链接不作为完整资料硬门槛。站内有可匹配数据时应建立链接，但不得把没有相关新闻误判为马资料不完整。

### 6. 来源 adapter 生成候选，不直接写主表

adapter 输出统一 payload：`profile_payload`、`pedigree_payload`、`race_records_payload`、`major_wins_payload`、`aliases_payload`、`source_evidence`、`raw_payload`、`confidence`、`failure_reason`。服务层再决定写 artifact、`HorseProfileDataCandidate` 或 commit 到主表。多来源字段冲突生成冲突候选，人工审核；同一字段只有高权威唯一来源时才可进入可批准 artifact。

首版 source authority 按地区定义初始优先级：日本 netkeiba/JRA/NAR；香港 HKJC；英国 Racing Post/Sporting Life/官方赛会；法国 France Galop/Geny；美国 Equibase/HRN/官方赛会。实现期可根据可用性和字段质量调整。

### 7. 审核按模块进行，完整计数按整匹马

artifact 和后台可按 `basic_profile`、`pedigree`、`race_records`、`major_wins` 模块审核。只有所有必需模块 approved 并成功写入后，才把该马计为完整资料样本。人工补录允许作为兜底来源，但必须记录来源 URL、录入人和审核人；只有来源 URL 无法公开复核或字段争议较大时，才要求额外截图/PDF/HTML 证据。

备选方案是整批自动高置信 commit。它会降低审核成本，但会把同名马、字段冲突和来源解析错误放大。

### 8. 首发人工，自动化分两条路径预留

资料补全和资料公开是两道门。首批完整资料马可进入 `ready`，并由人工选择每地区 1-2 匹发布做公开验收。未来自动化应区分：

- 已发布马资料的自动增量更新：可更早灰度，适合新增赛绩、同步最新履历和刷新完整状态。
- 未发布马资料的自动首次公开：必须有更硬门禁、地区/来源 allowlist、每日上限、回滚日志和灰度开关，另起 change。

### 9. 马匹身份采用来源内 ID 与数据库四元组两层证据

来源命名空间内的 external horse ID 可作为该来源的直接身份键，但不同来源的 ID 不能仅因值相同或不同就自动判断为同一匹或不同匹。对于数据库已有马，跨来源自动归并必须同时命中多语种马名、父名、母名和出生年份；马名及父母名通过正式术语主名、中文译名和多语言 alias 归一。同一赛事参赛者优先按马号或来源身份分组，不能先按同名折叠。同一来源的不同 external horse ID 可建立同名独立资料；跨来源证据不足或四元组多匹命中时写入专用 `HorseIdentityConflict`，即使尚无 `HorseProfile` 也必须持久化候选术语、原始证据和处理状态，并由每日运营通知提醒管理员处理。

### 10. 完整生涯按马采集，并与赛事产品覆盖解耦

`RaceEvent*` 继续表达赛事产品层，`HorseRaceRecord` 表达单匹马的参赛事实层。P0 马的完整生涯不能从重点赛事总账反推，必须按马匹来源采集全部实际出赛，包括新马、未胜利、普通条件、让磅、表列和各级分级赛。

- 有可靠赛事身份时，`HorseRaceRecord` 关联既有 `RaceEvent` / `RaceEventResult`。
- 没有可靠赛事身份时，保存未关联履历和比赛快照，不为普通比赛强行创建 `RaceEvent`。
- 后续确认赛事身份时，使用同一履历规范键回填关联，不新增第二条参赛事实。
- 来源内幂等键用于防止重复提交；跨来源规范键只在日期、场地和场次号，或日期、场地、比赛名、距离等证据足够时生成。证据不足时宁可进入审核，不做名称相似自动合并。
- 同一场海外远征在母国马匹页和举办地区来源中只生成一条履历，但在 `source_refs.sources` 中保留全部来源证据。

`HorseProfile.completeness_status` 继续表达基础资料/血统/整匹马聚合状态，同时新增独立 `career_history_status` 与计数快照。生涯完整仅在来源总实际出赛数已知、系统实际出赛数一致、无未解释缺口、无待确认出赛状态且逐场核心证据齐备时成立。`scratched`、`withdrawn` 不计入实际出赛；`did_not_finish`、`disqualified` 计入实际出赛。

### 11. 完整履历使用独立分页

公开马匹详情页默认按日期倒序，每页展示 20 条并提供正序/倒序切换。分页参数使用独立的 `records_page`，避免与页面其它列表冲突。已关联且公开的赛事显示可点击链接；未关联比赛只展示本地履历快照。请求路径只查询本地数据库。

### 12. 来源字段证据采用三层结构

逐场字段证据按 `direct_raw`、`canonical_raw`、`normalized` 三层保存。直接原始值表达当前页面实际展示；标准原始值表达 France Galop、IFCE SIRE 等当地权威来源的本地语义；归一化值只表达经过明确规则转换后的内部状态。三层分别保存来源 URL、时间和转换规则。

Sporting Life 可用于定位法国比赛和保留其展示值，但不得把 Class/Grade 自动当作 Groupe，也不得从舍入后的英制距离反推官方米制值。法国结果为 `N/A` 时，只有法国权威来源补证后才能填入标准原始值并归一化；没有证据的记录继续保持待权威补查。

### 13. 数量完整度与逐场权威性使用两个状态

`official_or_source_start_count`、`collected_start_count` 和 `gap_count` 表达数量是否对齐；`record_authority_status` 表达逐场记录是否来自已核验权威来源。官方总数与备用来源逐场行数相等时，缺口可以为 0，但状态仍是 `count_aligned_records_unverified`，不能提升为逐场官方完整。

美国短期允许人工核验 Equibase `Career Starts` 作为官方总数基准，并保留 URL 与核验时间。Equibase 免费页面受 Incapsula 和许可条款限制，生产代码不得用浏览器绕过方式抓取；长期使用 Equibase/Equineline/TrackMaster 授权数据或人工 Full Charts/Lifetime PP 复核。

HRN 默认只作为备用逐场来源。直接 slug、搜索结果、缓存复放和离线研究解析都必须让 HRN 页面马名、父名、母名、出生年份与已核验候选四字段全部存在且一致；缺项或冲突 fail closed。唯一窄例外是独立批准、精确绑定冻结输入与记录唯一性的组合来源审核：它可把该冻结研究派生物标为“组合来源逐场完整”，但不表示 HRN 或组合来源变成 Equibase 官方逐场履历，也不改变其它输入的默认状态。新增逐场权威性字段时，数据迁移把旧 `complete` 且权威性未核验的记录降为 `needs_review`，避免旧状态绕过新门禁。

所有地区缓存都必须使用缓存自身的马名或 alias 绑定请求马名，禁止以请求值回填缺失的来源身份。来源总数只有在来源名、来源 URL 和带时区核验时间齐备时才能参与 `complete` 判定。受控网络 client 只允许访问地区实现登记的 HTTPS 主机，transport 自动重定向必须关闭，并在每一跳发出请求前重新核验主机、凭据、端口和请求预算。迁移降级旧 `complete` 生涯时，原 `complete_profile_full` 聚合状态也同步撤销。

同一 provider 只有在候选和 payload 均携带一致 external horse ID 时可直接绑定；显式来源 namespace 与 `external:<provider>:...` key 必须一致。候选 provider 与资料 provider 不同时，必须由候选提供完整马名、父名、母名、出生年份并与 payload 一致，只有同名或 alias 不足以放行。总数证据和逐场权威白名单同时在 cache、normalizer、数据库生涯 evaluator、整匹马 evaluator、研究 JSON 与工作簿层执行，避免任何旁路把未知 authority 提升为完整。官方明确总出赛数为零时，空逐场列表是合法数量对齐快照；总数大于零时仍必须有逐场记录。

provider namespace 比较使用规范化值，允许来源名大小写差异；external horse ID 保持来源原值精确比较，不能因 provider 名规范化而放过不同 ID。官方总数证据 URL 使用 Django `URLValidator` 严格验证 HTTP(S) URL，空格主机、非法端口和其它不可解析值均不能参与完整度判定。

地区研究转换器必须只依赖候选 payload 自身：从逐场记录重新计算来源总数、实际出赛、未出赛、异常结果、海外出赛及双向数量差异，不能引用调用方临时变量或沿用旧 summary。日本 10 匹授权离线缓存必须能够逐匹重放转换器，作为真实回归门禁。

候选审核是追加式决策历史。新候选标为 `IGNORED` 只表示不采用本次建议，不撤销此前已 `APPLIED` 的有效模块证据；完整度读取最近一条非 ignored 决策。若从未存在 `APPLIED`，或最近非 ignored 状态为 `PENDING` / `CONFLICT`，模块仍保持阻断。

逐场状态在审核 artifact 和数据库之间使用同一模型枚举：第 4 名及以后、来源 `finished` 和来源 `unplaced` 均归一为 `unplaced`。年份精度履历继续保存，但只有完整日期可满足逐场核心证据门禁，避免 dry-run 显示完整而落库后立即变为 partial。人工基础字段、血统、逐场赛果、官方总数及佐证 URL 统一使用 Django `URLValidator` 校验 HTTP(S) 语法。

自动补充来源不得只凭同名并入主 payload。同 provider 只有双方 provider-bound external ID
完整且精确一致时可直接补空；其它情况要求主来源和补充来源各自都具备并一致命中马名、父名、
母名、出生年份。审核 apply 对行级 URL、模块 payload 和逐场 URL 再次执行严格验证，数据库
evaluator 对主 URL 与 `source_refs` 使用同一规则。来源总数、来源名、来源 URL 和带时区核验
时间是不可拆分的证据组；新候选缺任一项时整组清空，不能借用旧字段拼成有效证据。cache 的
硬字段还必须满足字符串、整数范围和 ISO 日期等类型/格式约束。研究摘要以“官方总数优先，
否则来源总数”的实际选定参照计算差异，不能在官方数已存在时继续拿备用来源数宣称对齐。

父母实体的二代血统反查同样遵守强身份规则。搜索结果中只有一个同名候选不构成自动身份；
只有预期 provider external ID 精确一致，或父名已知且候选自身具备名称、父、母、出生年、
provider external ID 和严格来源 URL 的完整来源身份时才可自动采用。provider namespace 可
规范化，external ID 只去首尾空格并按不透明原值精确比较。历史 name-only 血统证据若已由
人工审核，必须通过绑定原始输入 SHA、目标马强身份、父母实体 external ID、字段值、既有审核
上下文和独立出生年证据的逐行 manifest 升级；旧产物保持不变。出生年证据的审核主体按独立
artifact 记录，不得推导为项目负责人逐字段审核。历史 APPLIED 模块的 URL 也由最终数据库
完整度 evaluator 严格复核，不能因为记录早于新 apply 门禁而继续通过。

### 14. 父母来源身份与 v2 审核产物采用全局一致、版本化边界

父母实体不因只在某一字段行中出现而降低身份要求。每条 v2 `source_identity` 必须同时具备
`horse_name`、`sire_name`、`dam_name`、`birth_year`、provider namespace、provider-bound
external ID 和严格来源 URL；`116` 条已审核 pedigree evidence 可共享身份，但必须归并为
`55` 个全局唯一父母来源身份。provider namespace 可统一规范化，external ID 在搜索候选、
出生年证据、逐行 manifest、v2 JSON 和工作簿全链路按 opaque string 精确一致。

父母出生年由独立 approved artifact 提供，当前
`reviewed_parent_birth_year_evidence.json` 的 `reviewed_by=codex_manual_source_review`。
parent identity manifest 可绑定这份证据与既有项目负责人审核上下文，但不能把两者合并叙述为
项目负责人逐字段提供或审核 55 个出生年。

自动 Netkeiba 父母候选只接受精确
`https://en.netkeiba.com/db/horse/<id>/`；凭据、显式端口、query 或 fragment 均拒绝。纠错必须
显式保留 old/new identity 和原因：Kentucky Wood 的旧 Netkeiba `000a02bd3f` 是 1925 年同名
Balko，只留在 v1；v2 使用 Racing Post `595446` 的 2001 年 Balko，父母为 Pistolet Bleu /
Ella Royale。

v1 JSON 和工作簿作为冻结审计基线保持字节不变。工作簿 builder 默认读取 v2 JSON，写入
`-v2.xlsx` 与 `previews-v2`；环境变量覆盖配置文件。任何把冻结 v1 workbook 或 v1 previews
作为输出目标的运行必须 fail closed。

### 15. 美国组合逐场来源只通过冻结批次人工审核派生为完整

美国逐场记录的组合来源审核是对当前冻结批次的版本化人工裁决，不改变
`count_aligned_records_unverified` 的全局语义。审核 manifest 必须绑定 v2 输入 JSON 的字节
SHA、美国 10 匹马的名称/父名/母名/出生年四字段身份、Equibase 官方总出赛数证据、逐场记录
全集及稳定键摘要，并明确允许的逐场来源组成。

`prepare` 只能生成包含 `prepared_by/prepared_at` 的 pending artifact，不能接受审核人参数或
自行提升为 approved。独立批准 artifact 另行记录 `reviewed_by/approved_at`、
`decision_source_reference` 和“来源组合权威性决策、非逐字段人工复核”的 decision scope。
apply 同时要求代码内可信 v2 SHA、独立批准 artifact 的冻结 SHA 与调用方显式 SHA 三者一致；
调用方临时自制或自签 manifest 即使提供自身 SHA 也必须阻断。

当前获准组成只有两种：Fort George 精确为 HRN 6 条、Sporting Life 6 条、Racing Post 1 条；
其余 9 匹全部逐场记录来自 HRN。审核 artifact 缺失，或输入 SHA、身份、官方总数、记录内容、
稳定键、来源 URL、来源组成、缺口/超额/未知/冲突状态任一漂移时，整个审核 apply 必须 fail
closed，v2 仍保持 partial，不能按数量对齐自动提升。

每匹记录在审核前还必须复算 source-bound external result/race ID、完整稳定记录键和
“日期 + 马场 + 比赛名”同场规范键的唯一性。跨来源证据允许合并在同一记录的 `source_urls`
等来源引用中，但同一匹马不能用删一场、复制另一场的方式维持总数。

只有 manifest 与当前输入逐字义匹配时，离线 apply 才可生成
`p0-horse-research.v3` 研究派生产物，并仅将这 10 匹美国马提升为现有
`source_records_verified` 状态。apply 同时生成绑定 SHA 链的只读 module-review 与 production
readiness report；全程数据库写入数为零，不修改冻结 v1/v2，也不为该批次新增模型或枚举。
当前研究输入缺少真实 production profile ID、reviewer ID 和 commit-compatible 模块批准，
因此 readiness 必须为 blocked、`commit_artifact_compatible=false`，不能声称已完成正式
production dry-run。readiness 只记录 `static_schema_compatibility_check`：保留现有
`load_completion_artifact` 因 artifact type 不兼容而拒绝 v3 的真实结论，但
`safe_simulation_performed=false`；在正式 commit artifact 生成前不得伪造 apply 函数路径、
零动作 summary 或任何 simulation 已执行声明。

## Risks / Trade-offs

- [P0 范围膨胀] -> 重点赛事等级严格限定为 9 类，P0 身份必须有结构化来源证据。
- [无中文译名污染翻译] -> `translation_status=pending` 只参与识别和原文保护，不参与中文替换。
- [第三方来源限流或页面结构变化] -> 所有真实请求默认低频、限批、缓存；失败写入 artifact，不影响其它批次。
- [同名马或跨来源冲突] -> 来源内 external horse ID 只证明该来源身份；同场马先按马号/来源身份分组，跨来源合并必须完整命中“多语种马名 + 父名 + 母名 + 出生年份”。证据不足或多匹命中进入专用身份冲突表并定期通知管理员。
- [人工资料被覆盖] -> commit 前检查 `manual_lock_flags`，字段级跳过并输出 `manual_lock_skipped`。
- [首批地区数据源不足] -> 不降级验收；允许换样本、修 adapter 或人工补录。
- [生产批次耗时过长] -> 支持地区、profile id、limit、run 续跑和中断状态。
- [跨来源错误合并] -> 只有精确日期和足够赛事身份字段时生成跨来源规范键；弱证据保持独立并进入审核。
- [父母同名或来源 ID 漂移] -> 父母 `source_identity` 强制包含出生年和完整四字段身份，
  provider namespace 全局规范化但 external ID 按不透明原值精确一致；纠错只进入新版本。
- [计数快照漂移] -> 所有履历写入/关联入口调用统一重算服务，完整资料门禁以独立生涯状态为准；管理命令批量导入后仍需显式重算并输出 artifact。

## Migration Plan

1. 新增或扩展术语状态、P0 来源、补全 batch/run 和完整资料状态；本地执行 `makemigrations --check --dry-run`、`manage.py check` 和目标测试。
2. 更新术语解析、翻译提示、译后校验和术语应用逻辑，确保无译名 horse term 保留原文且不被空值替换。
3. 实现 P0 范围同步命令和队列预览，先在本地/生产备份副本 dry-run 五地区样本。
4. 为五大地区 adapter 生成候选 artifact；人工审核每地区 10 匹完整资料。
5. 生产 commit 前确认 `HEAD`、容器状态、`/healthz/`、外部导入运行数和导入锁，执行 `.env` 与数据库备份并 `gzip -t`。
6. commit 已审核 artifact，抽查 `HorseProfile`、`HorseRaceRecord`、P0 来源记录、无译名展示和翻译保护。
7. 人工发布每地区 1-2 匹完整资料马，验收前台索引、详情、移动端、关注、新闻 tag 和 no-network 边界。

回滚策略：

- 代码异常：回滚到部署前 commit 并重建服务。
- 迁移异常：优先使用部署前数据库备份恢复。
- 补全误写：按 artifact diff、候选记录和 batch 记录回退字段；大范围异常使用批次前数据库备份。
- 术语误影响翻译：关闭无译名术语参与翻译保护的开关或回退相关迁移/数据。
- 公开异常：先将受影响马匹批量改回 `hidden` 或 `draft`，再修复数据或代码。

## Resolved Questions

- 首批验收范围：五大地区各 10 匹完整资料马。
- 新版 P0 范围：当前有中文译名 active horse term + 五大地区重点赛事参赛马。
- 重点赛事等级：只包含 `G1/G2/G3/J-G1/J-G2/J-G3/JpnⅠ/JpnⅡ/JpnⅢ`。
- 时间范围：历史与未来全部已知重点赛事。
- 发布策略：首发人工，未来自动增量更新和自动首次公开分开设计。
- 马匹身份：`racing_region` 不属于身份键。来源内 external horse ID 可直接定位该来源身份；数据库已有马的跨来源自动归并使用“多语种马名 + 父名 + 母名 + 出生年份”，四项必须完整唯一命中。同一来源不同 ID 可建立同名独立资料；跨来源证据不足或多匹命中进入人工歧义，并每日通知管理员。跨地区参赛证据记录在 `HorseP0Source.racing_region`，不得覆盖马匹自身地区。
- 无译名保护：暂无中文译名的正式 horse term 原文保护跨地区生效，最终译文必须至少出现一次原始马名；已有中文译名且高度歧义的英文术语仍保留既有地区门禁。
- 来源撤销：普通 P0 同步只增量更新；只有显式全地区完整对账才按本轮全量可见来源撤销失效来源，标记 `revoked` 并保留历史，不删除证据。
- 审核门禁：artifact 顶层、行级和模块级审核缺一不可，审核人、置信度、冲突状态与来源 URL 均在写主表前校验。
- 父母来源身份：每个 v2 `source_identity` 必须含马名、父名、母名和出生年；provider namespace
  可规范化，external ID 全局按不透明原值一致。出生年证据独立审核，不能伪称为项目负责人
  逐字段审核。
- v2 产物：Balko 同名纠错显式留痕，工作簿默认使用 v2 JSON/输出/预览；冻结 v1 字节和输出
  目录受保护。
