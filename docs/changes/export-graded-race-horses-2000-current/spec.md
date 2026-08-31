# 四地区分级赛参赛马与完整资料回填规格

## 背景

本 change 将英国、爱尔兰、法国、美国指定年代和等级的全部实际参赛马纳入 UmaFans 马匹数据库，
并尽可能补齐公开单马页所需的基础资料、二代血统和完整生涯履历。结构化主数据使用用户现有的
The Racing API（以下简称 TRA）权限；赛事范围由独立年度分级赛底表定义，不能把 TRA 返回结果
本身当作应到分母。

生产只读基线（2026-08-29）显示，现有正式历史目标中，英国、法国、美国符合本 change 年份/等级
条件的赛事共 `10,063` 场，其中只有 `4,673 imported`；其余为 `4,856 pending`、
`521 source_unavailable`、`8 ready`、`5 identity_review_required`。相同筛选下当前
`RaceEvent` 有 `5,467` 场、`RaceEventResult` 有 `41,122` 行、赛果马名去重后已形成
`10,279` 个 P0 profile，但这些 profile 当前全部为 `completeness_status=empty`。

爱尔兰目前不是独立 `RacingRegion`；现有 TJCIS parser 会主动跳过 IRELAND/IRISH JUMPS，
而不是把它完整纳入英国。本 change 必须先补齐爱尔兰模型和底表，禁止把爱尔兰静默归到英国或
`other`。

## 目标

1. 建立不可静默缩减的四地区、逐届赛事应到总账。
2. 导出所有目标赛事的实际起跑马及 TRA provider identity。
3. 对范围内唯一马匹导出 TRA Pro profile、完整可用单马历史赛果和二代血统。
4. 复用现有 P0 reviewed-artifact、dry-run、apply、receipt 和 verifier 链路，把审核通过的数据
   幂等写入 `HorseProfile`、`HorseRaceRecord` 及正式 `RaceEvent/Result`。
5. 以官方/受控外部身份处理日本马、香港马及其他跨语言海外远征马，禁止名称单键合并。
6. 支持 checkpoint/resume、持久化请求预算、分批写入、重放零写和最终覆盖审计。

## 非目标

- 不把 TRA 标记为任何地区的官方数据商。
- 不把 TRA 的分析评论、performance rating、speed rating、赔率或彩衣直接公开到单马页。
- 不自动发布新 HorseProfile，不触发 QQ、邮件、新闻发布或 race-live。
- 不用无来源机器音译补中文、日文或香港官方名称。
- 不以一次大事务或一次长 Celery task 完成全范围。
- 不把外部站点整库抓取许可从本 change 的技术需求中推断出来。

## Requirements

### Requirement: 范围必须按赛事实际年度和当届等级判断

系统 SHALL 生成 `2000-01-01` 至运行日的赛事目标，地区固定为 Great Britain、Ireland、
France、USA。自然年 `2000–2020` 只纳入当届 G1；`2021–当前年` 纳入当届 G1/G2/G3。
赛事升级、降级、改名、移师或停办必须按当届证据处理，不能用当前等级回推历史。Listed、普通
让赛和未分级赛事不在范围内。

范围同时包含平地和障碍赛，只要当届在地区/国际分级目录中明确为 G1/G2/G3。当前年度未来赛事
保留为 `not_due`，只有已产生正式赛果后才进入参赛马分母。

#### Scenario: 2020 年当届 G2

- **WHEN** 某赛事在 2020 年为 G2，后来升级为 G1
- **THEN** 2020 届 SHALL 不进入本 change

#### Scenario: 2021 年障碍 G3

- **WHEN** 英国或爱尔兰一场障碍赛在 2021 年当届为 G3 且正式举行
- **THEN** 该届 SHALL 进入目标总账

#### Scenario: 当前年度未举行赛事

- **WHEN** 2026 年目标赛事尚未举行或没有正式赛果
- **THEN** 系统 SHALL 保留 `not_due` 或 `awaiting_result`
- **AND** MUST NOT 把它计入参赛马缺失率

#### Scenario: 执行日期越过原 not_due 赛日

- **WHEN** target catalog 仍绑定同一自然年，但执行 as-of 已晚于旧 `not_due.local_date`
- **THEN** 系统 SHALL 在同一 target SHA 上重跑 official calendar、coverage、occurrence 与 execution plan
- **AND** 旧 `not_due` SHALL 失败关闭并转回 `awaiting_result/past_schedule_needs_result`，不得继续排除出 due 分母
- **AND** 执行 as-of 不得早于 target catalog as-of 或跨入另一自然年
- **AND** 旧 plan/G3/proof SHALL 因完整 plan identity 改变而失效，即使下一批局部 target 恰好相同

### Requirement: 四地区必须独立建模

系统 SHALL 新增 `RacingRegion.IRELAND=ireland`，爱尔兰赛事使用 `Europe/Dublin`，TRA
region 使用 `IRE`。Great Britain 只接受 `GB`。现有明确带 IRE provider ID、爱尔兰马场、
TJCIS IRE section 或受审来源证据的记录 MAY 通过独立 reclassification artifact 调整地区；只有
名称或 “Irish” 文本不能触发批量改写。

#### Scenario: TJCIS 爱尔兰章节

- **WHEN** Blue Book 页面上下文为 `Pt I—IRE`、`IRELAND` 或 `IRISH JUMPS`
- **THEN** parser SHALL 输出 `country_region=ireland`
- **AND** 不得继续跳过或归入 `united_kingdom`

#### Scenario: 旧英国记录没有爱尔兰强证据

- **WHEN** 旧记录地区为英国，但没有 IRE/provider/马场受审证据
- **THEN** reclassification SHALL 保持原值并进入 review

### Requirement: 应到分母必须独立于 TRA 返回

系统 SHALL 由冻结的 TJCIS Blue Book 年度目录和逐地区官方/行业目录修正建立 target ledger。
每个 target 保存 `year/region/discipline/grade/series identity/name aliases/course/date status/
source URL/cache SHA/parser version`。TRA 未返回、第三方不可用或已有数据库缺失都不能删除 target。
series identity SHALL 在本次配置的全部年份集合上全局消歧；年度 parser 输出不得直接成为最终
`series_key`。同一 series 的升降级不改变身份；真正同名异赛才用马场、赛制、距离/场地等稳定事实拆分。
series 算法或 key 变化 SHALL 产生新 target artifact SHA，并使全部旧审核绑定失效。

完整性必须分别报告：

- `target_accounted`：held/not_held/not_due/superseded 守恒；
- `race_result_resolved`：已取得完整正式赛果的 held target；
- `participant_resolved`：所有实际起跑行身份可用；
- `horse_identity_resolved`：participant 已绑定唯一 canonical horse；
- `profile_complete`：单马页硬字段完整；
- `career_provider_complete`：TRA total 与分页结果守恒；
- `career_authority_complete`：逐场权威性与官方总出赛数另行闭环。

### Requirement: series inventory 与实际 occurrence 必须分层

`target_key=region:year:series_key:discipline` SHALL 只表示某系列当届是否属于本 change 的分级
范围；它不得被直接当作唯一比赛场次。系统 SHALL 另建 occurrence ledger，每个 held occurrence
至少绑定 `target_key/region/local_date/当届等级/马场/赛事原名/source payload SHA`，并优先保存
官方 result identity。一个 target MAY 对应多个 occurrence；一个 occurrence MUST NOT 绑定多个
target。

每个 target 必须由以下状态之一守恒：一个或多个 `held` occurrence、`not_held/cancelled`、
`not_due`、`superseded` 或明确 source gap。只有 `held` 且已有正式赛果的 occurrence 进入 starters
分母。无直接 chart URL 但有官方 date/grade/course/winner 的历史行 MAY 生成 targeted-horse anchor，
但只有 TRA 单马履历唯一反查到该场并恢复完整 runners 后才成为 resolved result。

occurrence compiler SHALL 只接受 hash-bound proposal root，不接受裸 JSONL 路径。每个输入必须重验唯一
marker、manifest、generator、target manifest/ledger/as-of 和 output member identity。即使 target 全部已
accounted，只要任一输入 `execution_ready=false`，输出 SHALL 保持 `needs_input_approval / PREPARED`，
不得生成 `COMPLETE`。

proposal 只有在独立 reviewer 的决定文件逐项绑定 proposal manifest、全部 output SHA、reviewer、带时区
时间、不可变审核记录引用和非实现者声明后，才能发布为 `APPROVED/execution_ready=true`。publisher SHALL
逐字节复制原输出，不得在批准时修改 occurrence/non-held facts，也不得把 proposal 的剩余 blockers 视为
已解决。

官方赛历匹配 SHALL 双向报告 target issue 和 source unmatched。目标与来源均有 G1/G2/G3 时等级
MUST 一致；唯一规范化赛名完全相等 MAY 优先于 OCR 距离，但必须保留距离质量问题。冠名、历史名、
OCR 断词和 Royal/`Park` 场地恒等只允许使用受审显式 alias，禁止降低 fuzzy 阈值或跨等级补位制造
零 gap。过去的 scheduled 日期 SHALL 标为 `past_schedule_needs_result`，不得直接变成 held occurrence。

target 的 `year` 是当届分级身份。held occurrence 的 `local_date` 通常位于同一自然年；只有原定赛日
取消/延期、实际补赛跨入下一自然年且有冻结来源、SHA、原定日期、实际日期、原因和人工审核记录时，
才允许 `local_date.year == target.year + 1`。公开赛事年份仍按实际 `local_date.year`，届次关联继续按
`edition_year=target.year`。普通跨年马季、搜索摘要或只有空 racecard 均不能触发该例外。

#### Scenario: 后续年份才出现同名异赛

- **WHEN** 早年只有一个短名赛事，后续年份出现同名但马场或赛制不同的另一赛事
- **THEN** builder SHALL 在全部年份汇总后一次性全局消歧
- **AND** 早年与后续年的同一系列 SHALL 使用相同稳定 key

#### Scenario: series key 算法改变

- **WHEN** 重建的事实行零增删但任一 `series_key/target_key` 改变
- **THEN** 旧 target audit、alias review、occurrence proposal 和 runnable seed SHALL 全部失效
- **AND** 下游只有重新绑定新 manifest 并完成对应审核后才可执行

#### Scenario: 同一系列一年举行两次

- **WHEN** TOBA 或地区官方来源证明同一 series 在同一自然年有两个不同日期的 held occurrence
- **THEN** occurrence ledger SHALL 保留两行并关联同一 target
- **AND** 不得按 series/year 或赛事名把两场折叠

#### Scenario: 地区来源只覆盖部分 discipline

- **WHEN** TOBA graded-stakes history 只列出美国平地赛，而同一目标窗口还包含美国障碍赛
- **THEN** flat source/target SHALL 单独完成 physical row、唯一 occurrence identity 与 target 双向守恒
- **AND** jumps target SHALL 标为该来源不支持并继续保留其他 authority/TRA 路由
- **AND** 不得把 jumps target 计入 TOBA unmatched 或因 flat review 完成而宣称美国总分母闭合

#### Scenario: 来源含重复 physical row

- **WHEN** 两条来源行生成同一稳定 occurrence identity
- **THEN** source census SHALL 同时保存 physical row count 与唯一 identity count
- **AND** 不得把重复行创建为第二个 occurrence 或隐藏来源质量问题

#### Scenario: 多个已审核来源指向同一实际赛事

- **WHEN** 不同 authority 的 reviewed rows 具有相同 `target_key + local_date`
- **THEN** occurrence ledger SHALL 只保留唯一最高 authority 的主 occurrence
- **AND** 其他来源 SHALL 作为 hash-bound corroborating references 保留，不创建第二场赛事
- **AND** 若最高 authority 不唯一，系统 SHALL fail closed，禁止按输入顺序任意选择
- **AND** 相同 target 但不同实际日期 SHALL 继续保留为不同 occurrences

#### Scenario: 目录列出但实际未举行

- **WHEN** 年初分级目录列出赛事，但官方年度结果标记 `not run` 或没有举行证据
- **THEN** target SHALL 保留并记录非 held disposition
- **AND** 不得为它创建空参赛马表或计入 participant 缺失率

#### Scenario: 官方赛历只有过去日期

- **WHEN** BHA/France Galop 赛历给出已过去日期，但没有完整结果或明确取消终态
- **THEN** 系统 SHALL 保存 `past_schedule_needs_result`
- **AND** 不得生成 winner、actual starters 或 runnable targeted-horse seed

#### Scenario: 官方名称精确但 OCR 距离冲突

- **WHEN** 同地区、年份、场地、等级中只有一个规范化赛名完全相等，但 PDF OCR 距离与 target 不一致
- **THEN** 系统 MAY 选择该唯一名称候选并记录距离质量问题
- **AND** 不得改配到名称较弱的相邻赛事

#### Scenario: 来源等级与目标等级冲突

- **WHEN** target 为 G3、官方来源明确为 G2
- **THEN** 系统 SHALL 保留 grade conflict/source gap
- **AND** 不得忽略等级或占用其他 target 的来源行

#### Scenario: 官方历史行没有 chart URL

- **WHEN** 官方分级机构历史表提供 date/course/grade/winner/field size，但没有逐场 chart 链接
- **THEN** 系统 MAY 使用冠军名和唯一 occurrence 作为 targeted-horse seed
- **AND** 不得把“没有 chart URL”解释为“赛事未举行”

#### Scenario: 年末取消后次年补赛

- **WHEN** 2015 届分级赛原定 2015-12-27 的整个赛日取消，并有正式结果证明赛事于 2016-01-09 举行
- **THEN** occurrence SHALL 保存 `edition_year=2015` 与 `local_date=2016-01-09`
- **AND** 必须绑定原赛日取消证据、实际结果证据、各自缓存 SHA 和人工审核元数据
- **AND** 不得把原定 racecard 的 declared runners 当作实际 starters

### Requirement: 实际参赛语义必须来自正式赛果

参赛马 SHALL 是正式赛果中具有实际起跑证据的 runner。数字名次、同着、PU、F、UR、DNF、DSQ
等赛后状态保留；NR、scratched、withdrawn 和仅出现在赛前 racecard 的马排除。未知状态进入
`participant_status_unresolved` 并阻断该行，不得猜测。

一个赛事结果必须按 `TRA race_id + canonical payload hash` 去重。单马 results 会返回完整赛事
和全体 runners；多个目标马带回同一赛事时只能保存一个 race observation。经目标总账确认的目标赛事
中的全部实际出赛 runner SHALL 转成显式、去重的 `hrs_*` enrichment scope；但这些马的生涯结果中
出现的其他同场马不得继续递归扩展。也就是说，扩展边界是“受审目标赛事的实际出赛马”，不是任意
career graph。

历史 target 已取得完整结果但尚无正式事件时，必须先通过现有 historical calendar admission、
reviewed detail package 和 receipt 链创建/更新 `RaceEvent/RaceEventResult`，再生成 participant
资格和 `HorseRaceRecord`。只存在 ExternalRace staging 不算赛事落表完成。

### Requirement: TRA 必须支持两条互补导出路径

系统 SHALL 提供：

1. `bulk_results`：对 `/v1/results` 按单个当地日期、region 分页；适用于账号 entitlement
   允许的 2005 年以后范围。
2. `targeted_horse`：读取 SHA 锁定的外部马名/赛事锚点，依次调用
   `/v1/horses/search`、`/{horse_id}/pro`（404 回退 standard）和
   `/{horse_id}/results`；用于单马补抓、2000–2004、批量历史权限缺失或赛果缺口。
3. `target_runner_stable_id`：从已完成的 `targeted_horse` 目标赛事中提取全部实际出赛 `hrs_*`，
   跨赛事去重后直接调用 `/{horse_id}/pro|standard` 与 `/{horse_id}/results`；不得再次按名字搜索。

`targeted_horse` 外部 seed 必须至少保存来源赛事、来源 URL、原名/拉丁名，并尽力提供国别、
出生年、性别、父、母。搜索结果不得取第一条。唯一强身份既可以是完整 DOB/sex/sire/dam，
也可以是受审来源声明的唯一赛事 occurrence；后者必须逐个候选读取 horse results，并且只能有一个
provider horse 在目标赛事满足该名次。`targeted-horse-seed.v1` 继续要求精确
date/course/race/grade；仅限 2000–2004 的 `targeted-horse-seed.v2` 可在来源确实没有日期时省略
`local_date`，但必须同时固定 `edition_year`、region、canonical race name/aliases、canonical
course/aliases、grade、discipline、冠军名次和全部来源 SHA。此时 matcher 仍须在该马完整 career 中按
year + race aliases + course aliases + grade + discipline + position 得到唯一 occurrence；日期存在时是
额外硬过滤条件。缺任一结构化赛事字段、同年多解或两个 provider candidate 均命中时，终止为
`search_ambiguous`，不得用名称单键确认身份。

外部来源取得的冠军名不得直接成为 runnable seed。系统 SHALL 先读取 SHA 锁定的批量 anchor index，
逐行验证 reviewed COMPLETE target、单一冻结结果页、request ledger、winner reference、来源 URL/页面
payload SHA、日期精度/等级/冠军名次，并输出 `PREPARED_NOT_EXECUTABLE` proposal。一个冻结结果不得复用到
两个 target。只有非实现者的独立决定文件同时绑定 proposal manifest 和全部 seed/evidence output SHA，
且保存带时区审核时间与不可变审核记录引用后，publisher 才可逐字节发布
`targeted-horse-seed-ledger.v1 / COMPLETE`。该 COMPLETE 只批准锚点事实；每个 TRA 网络批次仍需新的精确
G3，不得从单页人工引用推导来源站的系统化抓取/复用许可。

pre-2005 readiness 中已确认未举行或取消的 target 不得生成 winner seed。它们 SHALL 进入独立
calendar-correction proposal，逐条绑定 target、原因、上游 source proposal manifest SHA 与 candidate-row
SHA；当来源本身提供 row-level URL/page payload 时还必须一并绑定。若 row-level URL/page SHA 不存在，上游
manifest 必须仍能确定性重放冻结 cache、候选行和取消分类，不得以空 URL 免除来源审计。只有
`CALENDAR_CORRECTION_PUBLICATION_ONLY_NO_DATABASE_WRITE` 范围的非实现者 exact-SHA decision 才能发布
approved correction ledger；该批准仍不允许数据库 apply。seed、correction、unresolved 三个集合必须互斥并
覆盖全部 pre-2005 target。

#### Scenario: 从其他来源取得一批冠军名

- **WHEN** 外部受控来源为一批 target 提供唯一 date precision/course/grade/winner 关系并冻结页面 SHA
- **THEN** 系统 SHALL 为每个 target 生成一条不可执行 seed/evidence pair
- **AND** 任一 target、页面、request ledger、解析结果或索引 SHA 漂移 SHALL 使整批失败关闭
- **AND** 独立审核通过后也只允许把冠军作为 TRA 定向赛事恢复锚点
- **AND** 不得把来源页面的其他 runner 自动视为 TRA 已导出数据

#### Scenario: 1999 凯旋门冠军

- **WHEN** 输入经来源验证的 Montjeu seed（1999 Arc winner、1996、IRE、Sadler's Wells、
  Floripedes）
- **THEN** runner SHALL 验证唯一 TRA horse identity
- **AND** 获取 Pro profile 与全部分页 horse results
- **AND** 核对 1999 Arc 是否存在
- **AND** 关键赛事缺失时终态为 `provider_partial`，不得宣称完整

#### Scenario: 2000–2004 赛事锚点恢复

- **WHEN** 某目标赛事不在 bulk results 可查询年代，但外部权威/受控结果源能提供该场一个唯一
  实际起跑马
- **THEN** 系统 MAY 通过该马的 full historical results 定位唯一赛事并取得完整 runners
- **AND** race name/date/course/pattern 任一形成多解时必须 review

#### Scenario: pre-2005 来源缺少精确日期

- **WHEN** 冻结来源只证明 edition year、冠军、赛事名、马场、等级和 discipline，且没有可信精确日期
- **THEN** proposal SHALL 生成不可执行的 `proposed-targeted-horse-seed.v2` 并显式保存
  `date_precision=edition_year_only`
- **AND** 独立批准后发布的 `targeted-horse-seed.v2` SHALL 只在完整 career 中按全部结构化赛事字段和冠军名次
  唯一命中时接受
- **AND** 同年同名赛事多解、马场/等级/discipline 漂移或多个 exact-name horse 候选命中 SHALL fail closed
- **AND** seed approval SHALL 不构成 TRA 网络 G3 或数据库写入授权

#### Scenario: pre-2005 取消与未举行赛事

- **WHEN** reviewed readiness 将 target 归类为 not-held/cancelled correction
- **THEN** 该 target SHALL 不生成 winner seed，也不得进入 TRA request plan
- **AND** correction proposal 与 seed proposal SHALL 使用独立 output、decision scope 和 publisher
- **AND** row-level URL/page SHA 缺失时 SHALL 以可重放的上游 source proposal manifest + candidate-row SHA
  证明来源，不得只保留无来源的取消原因字符串
- **AND** approved correction ledger 仍 SHALL 保持 `database_apply_approved=false`
- **AND** 最终守恒 SHALL 为 `winner seeds + approved corrections + unresolved = pre-2005 targets`

#### Scenario: 外部来源只提供冠军名和赛事关系

- **WHEN** 受审来源只证明“Montjeu 是 1999 Arc 冠军”，没有 DOB 或父母
- **THEN** 系统 SHALL 对所有 exact-name search candidates 检查 full horse results
- **AND** 只有一个 `hrs_*` 在唯一 1999 Arc race 中名次为 1 时才可绑定
- **AND** 两个候选均命中、赛事多解或名次不符时必须 `search_ambiguous`

#### Scenario: 由冠军锚点补全整场实际参赛马

- **WHEN** 唯一冠军 `hrs_*` 的 full historical results 已定位一场受审目标赛事
- **THEN** 系统 SHALL 保留数字名次、同着、PU/F/UR/DNF/DSQ 等所有实际出赛 runner
- **AND** 排除 NR/scratched/withdrawn 与未知状态
- **AND** 按 `hrs_*` 跨目标赛事去重并生成稳定 ID 补全总账
- **AND** 补全阶段 SHALL 不调用 `/horses/search`
- **AND** 每匹马 SHALL 重新在其 career 中验证总账列出的全部目标赛事和 race payload hash
- **AND** 生涯其他赛事的同场 runner 不得自动成为新的完整 profile/career 任务

#### Scenario: stable ledger 只引用 held census 的局部 target

- **WHEN** stable ledger 只引用已批准 held seed 集合中的部分 target
- **THEN** scoped reconciliation MAY 只选择这些 exact source seed 对应 target
- **AND** 每个被选 target 内的 source census 与 TRA runner 仍 SHALL 数量守恒、逐马唯一绑定且零 review/gap
- **AND** stable source seed 不在 approved held map 时 SHALL fail closed，不得借局部模式绕过来源批准
- **AND** scoped approval SHALL 不代表未选择的 held target 已完成 reconciliation

#### Scenario: 多种已批准来源共同覆盖 stable occurrences

- **WHEN** 一部分 occurrence 来自 COMPLETE held reconciliation，另一部分来自 COMPLETE external-result
  single-race approval
- **THEN** 系统 SHALL 按 `(horse_id, race_id, source_targeted_seed_id)` 构造 canonical occurrence key
- **AND** 所有组件的当前 manifest、upstream stable payload、decision 与 member set SHALL 逐项重验
- **AND** 组件并集 SHALL 与 stable ledger occurrence 集合完全相等，任一 overlap 或 gap 均 fail closed
- **AND** COMPLETE coverage SHALL 只授予 `planning_eligible`，不得授予网络或数据库写入
- **AND** stable-ID planner SHALL 继续保持 `search_requests_per_seed=0`

#### Scenario: 下一批在 fresh proof 前做只读 preflight

- **WHEN** 下一批已有 exact G3 approval，但尚未取得限时 exclusive proof
- **THEN** 系统 SHALL 能只读重验 plan、execution ledger、approval、seed、OpenAPI、output/budget 路径和全部
  network command 参数
- **AND** preflight SHALL 不读取 proof 或凭据、不创建 output/budget、不 claim、不修改 ledger/lock
- **AND** 任一参数、SHA、next ordinal、间隔或路径身份漂移 SHALL 在 proof 前 fail closed
- **AND** preflight 通过只表示 `ready_for_fresh_exclusive_proof`，不得解释为已获 proof 或已联网

#### Scenario: 首个 live scope selection 驱动单命令 preflight

- **WHEN** 多个 G3 首批均已批准且 preflight-ready
- **THEN** 系统 SHALL 以私有、SHA/COMPLETE 绑定的 selection artifact 唯一选择一个 scope
- **AND** selection SHALL 固定所选 plan/G3/ledger/lock/seed/OpenAPI/路径/参数与预期 preflight 投影
- **AND** 单命令 auditor SHALL 只接收 selection root + SHA，拒绝重复 JSON key、布尔冒充整数、marker/SHA/
  projection/path 漂移
- **AND** auditor SHALL 比较 ledger/lock 前后 SHA并确认 output/budget absent
- **AND** audit ready 仍 SHALL 不授权 proof、claim、network 或 database write

#### Scenario: selected batch COMPLETE 后生成不可执行后处理计划

- **WHEN** selected scope 的 batch 已由 execution ledger 记录为最新 COMPLETE 且 ledger `active=null`
- **THEN** 系统 SHALL 重验 batch manifest/marker、完整 materialization、seed set、唯一 `hrs_*` 与每个 run
  manifest SHA
- **AND** 系统 SHALL 冻结逐马 diagnostic dry-run、原子 batch staging apply、candidate batch 与全量 identity census 参数
- **AND** 后处理计划 SHALL 固定为 `PREPARED_NOT_AUTHORIZED`，staging/module/canonical write authority 全 false
- **AND** candidate 实际生成前 SHALL 不得填充 module review candidate SHA 或发布审核批准
- **AND** active/后续 ledger 项、非全量 materialization 或任一 source/identity/SHA 漂移 SHALL fail closed

#### Scenario: 完整 materialization 原子写入 External staging

- **WHEN** exact-SHA materialization 已通过全批 dry-run，且另行满足 staging write gate
- **THEN** 系统 SHALL 在单一外层数据库事务中按 ordinal 应用全部 immutable 单马 artifact
- **AND** 任一后段 run 失败 SHALL 回滚本事务内更早 run 的 horse/race/result/history/receipt 写入
- **AND** 已存在的成功单马 receipt SHALL 幂等 replay，并在 batch report 中逐项列出 applied/replayed
- **AND** batch apply SHALL 继续要求环境开关和显式 `--apply --allow-write`
- **AND** External staging SHALL 不创建 canonical identity，也不得解释为最终业务落表完成

#### Scenario: candidate batch 精确驱动 identity 与 module review proposal

- **WHEN** 完整 materialization 已进入 External staging 并生成逐马 P0 candidate
- **THEN** 系统 SHALL 原子发布 candidate files、batch manifest 与最后 `PREPARED`，并绑定每个 source run SHA
- **AND** 同一 batch 的 provider `hrs_*` SHALL 唯一；重复 stable ID SHALL 在输出前失败关闭
- **AND** 任一 candidate blocked SHALL 使整批成为 `PREPARED_BLOCKED`，不得跳过问题马进入 module review
- **AND** 全体 review-required/zero-blocker 时 SHALL 允许 identity/module `prepare-batch` 分别重新验证同一 exact
  member SHA 集合；batch 模式 SHALL 拒绝 individual candidate 混入
- **AND** candidate batch、identity proposal 和 module proposal SHALL 均保持 network/database writes=0，且不授权
  publish/apply

#### Scenario: current completion audit 守恒 candidate batch 与 proposals

- **WHEN** candidate batch、identity proposal 与 module proposal 都已生成
- **THEN** current completion audit SHALL 以 exact batch manifest/PREPARED 重验 source materialization/batch、
  全部 candidate source-run/path/SHA/size/status/blocker、唯一 `hrs_*` 与精确成员集合
- **AND** identity/module proposal SHALL 引用同一 candidate path + SHA 集合
- **AND** batch 输入与逐文件兼容输入 SHALL 互斥；额外成员、symlink 或任一漂移 SHALL 在输出前 fail closed
- **AND** audit 输入 SHALL 拒绝任意层重复 JSON key 与非有限数值
- **AND** 缺少 reviewed approval、production receipt/inventory 或 public verifier 时，结果 SHALL 保持
  `AUDITED_INCOMPLETE`，不得声称完成

#### Scenario: 全局 canonical inventory 以 merged hrs_* 分母只读核验生产终态

- **WHEN** exact frozen-plan `N_bulk` + 65 pre-2005 targeted merged stable ledger 已完成且准备核验 canonical 数据库
- **THEN** inventory SHALL 严格重验 merged v2 manifest、COMPLETE marker、唯一 `hrs_*` 与 occurrence/horse 计数
- **AND** merged manifest SHALL 恰含 `N_bulk+65` 个唯一 source stable identities；少于两个 exact frontiers 的 pilot 或
  部分 ledger SHALL 在数据库查询前 fail closed
- **AND** 每个 `hrs_*` SHALL 恰有一个 `the_racing_api:horse` verified external identity，并指向唯一 canonical profile
- **AND** 每个 verified identity SHALL 由状态为 applied、未 reverse 且 live after-state 仍一致的 identity review
  receipt 覆盖；手工或漂移的 verified 行不得冒充本批审核完成
- **AND** 两个 provider ID 指向同一 profile SHALL 在两个 inventory rows 上同时阻断，不得按输入顺序只标后一行
- **AND** profile SHALL 通过 full-profile completeness、complete career、source-record authority、zero-gap、published 状态
  与 public path 合同
- **AND** 每个 profile SHALL 由未 reverse 的最新 production apply receipt 覆盖；只验证最后有效 receipt 的 live
  after-state，合法后续 apply 不得使旧 receipt 被误当最终终态
- **AND** production apply SHALL 将本马 exact module-review approval manifest SHA 随 identity key 持久化；inventory
  SHALL 同时输出 identity receipt artifact SHA 与该 module approval SHA
- **AND** 最新 receipt 的 live state 漂移、缺 receipt、缺 identity、identity 非 verified 或 profile 不完整 SHALL 形成
  row blocker 并保持 `INCOMPLETE_READ_ONLY`
- **AND** inventory SHALL 输出 exact public-page target 清单，但固定 network requests/database writes=0，且即使 canonical
  DB 全部通过也保持 `completion_achieved=false`，直到独立 public verifier 完成
- **AND** stable ledger extra member、symlink、重复 JSON key、非有限数、SHA/size/count/path 漂移 SHALL 在查询终态前
  fail closed

#### Scenario: 独立公开页验收回绑全部 canonical profile 与分页履历

- **WHEN** canonical inventory 为 exact-SHA `COMPLETE_READ_ONLY` 且全部 public targets 可验收
- **THEN** verifier SHALL 先离线生成 immutable plan；每匹马第一页使用固定 public path，后续页仅使用
  `records_page=N`，并回绑 inventory manifest、`hrs_*`、profile ID、履历总数、页数、逐页 record ID 与 canonical key
- **AND** plan 阶段 SHALL 固定 network/database writes=0、execution authorized=false；真实执行 SHALL 同时要求
  CLI `--allow-network` 与环境变量 `RACING_API_PUBLIC_VERIFY_NETWORK_ENABLED=true`
- **AND** 真实 client SHALL 只允许 UmaFans HTTPS host、拒绝 credentials/port/redirect，禁用环境 proxy/netrc，限速不低于
  0.5 秒/请求，并将单页响应硬限制为 5 MiB
- **AND** 每页 SHALL 验证 HTTP 200、exact final URL、HTML content type、唯一 horse main identity、profile/count/page/pages、
  基础资料/血统/参赛履历标题、必要字段、主胜鞍与 exact page record order
- **AND** 每个 response body、逐页 blocker 与 aggregate SHA SHALL 写入 immutable evidence；任一页失败时状态 SHALL 为
  `INCOMPLETE_READ_ONLY`，HTTP 200 或抽样通过不得替代全量完成
- **AND** 单次网络执行 SHALL 最多覆盖 50 个连续 request ordinals；最终 merge SHALL 零联网重验每个 chunk 的
  manifest/marker/rows/response bytes，并要求 `1..request_count` 无 gap、overlap 或 extra member
- **AND** public verifier 自身不授予 production apply/profile publish/DB write，final global audit 前仍保持
  `completion_achieved=false`

#### Scenario: final global audit 逐马闭合审核、数据库与公网 lineage

- **WHEN** exact global review aggregate、canonical inventory 与 merged public verification 均为 complete artifact
- **AND** review aggregate 前置 binding SHALL 由 complete/inactive global enrichment execution ledger 自动生成；
  materialization、candidate、identity proposal/approval、module proposal/approval 六个 parent 的 child set 必须各自
  恰等于 planned batch IDs，禁止人工逐行拼接或混入 pilot
- **THEN** review aggregate SHALL 重放每个 candidate batch、identity proposal/approval、module proposal/approval，且
  每批马集合互斥、并集恰等于 frozen-plan `N_bulk+65` source merged stable `hrs_*` 分母
- **AND** automatic binding wrapper 与 aggregate SHALL 分别重验 exact marker/member/SHA/proposal/decision/horse set；
  wrapper COMPLETE 不得替代 aggregate 独立 replay，二者都不授予 review/apply/publish 权限
- **AND** final audit SHALL 要求 review/inventory/public 的 stable identity、provider set SHA、horse count 与 public-plan
  inventory binding 完全相等
- **AND** 每匹马的 identity approval artifact SHA SHALL 等于 applied/unreversed identity receipt artifact SHA，module
  approval manifest SHA SHALL 等于 live-verified production receipt 持久化的 SHA
- **AND** 只有全部逐马 lineage 与 public contract 通过时 SHALL 原子生成
  `AUDITED_COMPLETE / completion_achieved=true`；任一缺失或漂移 SHALL safe-stop 且不创建输出目录
- **AND** aggregate/final audit 自身 SHALL 固定 network/database writes=0，且不授予 review/apply/publish/fetch 权限

#### Scenario: bulk actual starters 进入全局 stable-ID 补全主线

- **WHEN** 一个 bulk range batch 已是 exact-SHA `COMPLETE` 且 target reconciliation 零 gap
- **THEN** 系统 SHALL 重验 plan/target ledger、request/response cache、normalized reconciliation、member set 与
  actual-starter/NR 守恒，再输出 provider-native stable-ID ledger
- **AND** 每条 occurrence SHALL 绑定 bulk run、target key、race/runner payload SHA 与唯一 `hrs_*`
- **AND** 系统 SHALL 只读证明每个 COMPLETE execution receipt 恰有一个 exact stable ledger；只有所有计划批次
  COMPLETE、全部 stable ledger 一一齐套且 execution active 为空时，才可输出最终 global merge inputs
- **AND** pre-2005 targeted compact route SHALL 先逐批生成 exact full materialization，再生成 stable ledger；只有
  65/65 receipt/materialization/stable 两段一一齐套且 inactive 时，才可输出该分区 merge inputs
- **AND** 每个 pre-2005 COMPLETE materialization SHALL 作为 `provider_native_targeted_materialization` component
  精确覆盖其 actual-starter occurrences，并且其唯一 source stable SHALL 属于最终 merged lineage
- **AND** 最终 occurrence merge source set SHALL 恰为冻结 batch plan 的全部 bulk stable + 65 个 pre-2005 targeted stable；已被
  bulk 覆盖的 France/Ireland 13 马 pilot occurrence ledgers SHALL 排除，不得作为额外 authority 重复并入
- **AND** global coverage build SHALL 先证明 merged v2 manifest 的全部 source root/SHA 与两个 frontier 完全相等，
  再生成且只生成 `N_bulk` 个 bulk-run + 65 个 targeted-materialization components；本次 `N_bulk=88`
- **AND** coverage COMPLETE 后 SHALL 再以同一 frontiers 重验 exact `N_bulk+65` component set、全部 occurrence/horse 与
  unique `hrs_*`；只有守恒时才输出 zero-search planner argv，不得手工从 coverage 跳过该门禁
- **AND** zero-search plan 的 materialization/candidate/identity/module children SHALL 分别形成 COMPLETE execution
  batch IDs 的连续前缀；candidate SHALL 在 proposal handoff 前回绑 exact materialization/source batch/run 与计划 horse set
- **AND** staging dry-run、candidate/identity/module proposal SHALL NOT 授权 staging apply、review approval 或 production apply
- **AND** targeted materializer 与 External staging SHALL 对 batch/run/materialization manifest、seed/compact/normalized、
  response wrapper 使用 duplicate-key-free、non-finite-free JSON；重算 SHA/marker 后仍有歧义 SHALL fail closed before DB
- **AND** 已验证 proposal prefix MAY 在后续 batch 等待时进入人工 identity/module review；approval children SHALL
  分别形成 validated proposal IDs 的连续前缀，orphan/extra/跳批 SHALL fail closed
- **AND** identity handoff SHALL 固定 proposal/rows/decision-template SHA 并要求 reviewed decisions SHA、reviewer、
  reference/time；module handoff SHALL 固定 review rows 并要求逐马四模块与 source-record authority 人工核对
- **AND** identity handoff SHALL 将 rows 分为 verified-ID reconfirmation、official/local crosswalk、strong biodata、
  observed-ID、create-new cross-language duplicate review 与 ambiguous/blocked cohorts；每组仍 SHALL manual-review，
  template/recommended-action drift SHALL fail closed，任何 cohort 不得自动批准
- **AND** frontier SHALL NOT 自动 publish approval；只有全部 planned batches 的双 approval exact-match 后，才 MAY
  自动执行 network/DB=0 的 immutable binding artifact generation，且不得外推 production apply 权限
- **AND** module approval publisher SHALL 从每个 exact candidate path/SHA 逐行重建 review row 与 deterministic
  manifest；即使 rows、manifest、marker 同时被重算，任何 proposal/candidate replay drift 仍 SHALL fail closed
- **AND** module candidate/proposal/approval JSON/JSONL SHALL 拒绝 duplicate keys 与 `NaN/Infinity`，不得让同一 SHA
  artifact 在不同 JSON parser 下存在多种解释
- **AND** identity candidate/proposal/reviewer-decisions/approval JSON/JSONL SHALL 使用同一 duplicate-key-free、
  non-finite-free 合同，不得因 decoder 分叉放宽
- **AND** 全部 bulk/targeted stable ledgers SHALL 先跨批 merge，以 provider ID 全局去重并保留所有 target occurrences
- **AND** merged ledger SHALL 由 provider-native bulk、provider-native targeted materialization、held 与 external
  components 做 exact occurrence coverage；任一
  overlap/gap/source-lineage 漂移 SHALL fail closed
- **AND** enrichment planner SHALL 只消费完整 merged coverage，不得开放单 bulk batch 直达 enrichment 的旁路

### Requirement: 单马页硬字段必须逐字段评估

单马页硬字段分为：

- 身份/名称：canonical profile、原名或英文名、地区/出生国；
- 基础：出生日期、性别、毛色、生产者；马主/练马师以带 as-of 的最新来源 observation 候选；
- 血统：父、母、父父、父母、母父、母母；
- 履历：全部已取得实际出赛记录、出赛/冠/亚/季统计、主胜鞍；
- 审计：来源 URL、provider ID、payload hash、抓取时间、完整性状态。

TRA 不能提供中文名、日文注册名、香港官方繁中名、简介和本地官方注册 ID。这些字段必须复用
现有审核数据或本地官方 crosswalk；缺失保持 unknown。 `intro`、相关新闻和公开发布状态不作为
本次数据导入 blocker。

主胜鞍只由已导入 `HorseRaceRecord` 中实际获胜且当届 G1/G2/G3 的赛事确定性计算，不能复制
供应商摘要文本。

#### Scenario: 字段矩阵生成 P0 审核候选

- **WHEN** materialized 单马 artifact 已绑定 normalized JSON、字段矩阵及全部 HTTP response wrapper
- **THEN** 系统 SHALL 生成 `database_writes=0` 的审核候选
- **AND** profile 字段 SHALL 回溯到同一马的 Pro/Standard response
- **AND** 每条履历 SHALL 回溯到包含同一 race ID 的 full-results response
- **AND** provider career 守恒但逐场 authority 未审核时 SHALL 保持
  `count_aligned_records_unverified / review_required`

#### Scenario: search 消歧响应不得污染目标马证据

- **WHEN** 同一 materialized artifact 包含严格的 `/horses/search?name=...` 或 `?q=...` 响应
- **THEN** search response SHALL 只用于稳定 ID 发现，不得给 profile、parent 或 career 字段背书
- **AND** 非目标马 `/results` 只有在其 `hrs_*` 已由同一冻结 search response 披露时，才可作为
  `discovery_probe` 排除出 `source_evidence`
- **AND** target profile payload、每个声明 parent payload SHALL 分别与 normalized payload SHA 精确一致
- **AND** 未披露 horse endpoint、未声明 parent endpoint、credential/host/query 漂移或 payload SHA 漂移
  SHALL fail closed
- **AND** 下游 identity/module review SHALL 重新验证所有 candidate evidence URL，仅从目标马 profile/results
  计算身份与 career coverage；安全 parent profile 旁证不得被误算成目标马证据

#### Scenario: 候选不得越过人工与跨语言身份门禁

- **WHEN** 候选字段与 `manual_lock_flags` 冲突
- **THEN** 系统 SHALL 返回 `manual_lock_conflict` 且不改写 profile
- **AND** 日本或香港新 profile 没有 JRA/JBIS/HKJC 官方 crosswalk 时 SHALL 阻断
- **AND** 已审核 `HorseNameVariant` SHALL 进入 mapping 名称召回与 snapshot SHA
- **AND** variant 后续漂移 SHALL 使旧 mapping decision 失效

#### Scenario: official 标记不能单独构成跨语言身份授权

- **WHEN** `HorseNameVariant.is_official=true` 且同时链接 TRA horse 与 canonical profile
- **THEN** 系统 SHALL 同时要求完整 evidence URL/payload SHA；日本/香港 profile 必须再有与已审核本地
  identity namespace 一致的 JRA/JBIS/NAR/HKJC authority host，其他地区才可使用
  source/region/authority host 一致的一等官方来源
- **AND** 任一证据缺失、authority host 与 namespace 不一致或 source 与地区不一致时不得返回
  `bind_official_crosswalk`
- **AND** authority URL SHALL 指向 horse record 路由且其 record ID 与 verified local key 一致；同一 authority
  host 下另一匹马的页面不得满足 crosswalk
- **AND** 一个可信 crosswalk 与指向另一 profile 的未可信 official claim 并存时 SHALL
  `blocked_official_crosswalk_conflict`
- **AND** proposal snapshot SHALL 包含 variant 的 external linkage、有效期、evidence URL 与 payload SHA，
  审核后任一漂移均使批准失效

#### Scenario: production identity census 是只读冻结输入

- **WHEN** operator 对全部 staged TRA horses 或显式 `hrs_*` 集合生成 identity census
- **THEN** 系统 SHALL 按 provider horse ID 排序，逐马冻结 ExternalHorse snapshot、resolver decision、当前
  identity、trusted/untrusted official claims 与全部 candidate profile snapshot
- **AND** artifact SHALL 保存 scope provider-ID set SHA、row/manifest SHA、disposition/region/claim counts，
  并声明 `network_requests=0 / database_writes=0`
- **AND** provider ID 缺失、重复、非法、输出目录已存在、naive 时间或数据库 snapshot 漂移时 SHALL fail closed
- **AND** 相同 DB snapshot、scope 与 timezone-aware generated-at SHALL 逐字节重放一致

### Requirement: 二代血统必须有界递归

目标马 Pro/Standard profile 给出的 sire/dam/damsire ID SHALL 保存。为补全父父、父母、母父、
母母，系统 MAY 将 `sir_/dam_/dsi_` 转换为 `hrs_` 读取父母 profile；所有 parent ID 全局去重，
最大深度为 1（从目标马到父母），不递归建立整个族谱。不存在的 parent profile 保持 gap。

### Requirement: 跨语言身份不得只按名称合并

TRA `hrs_*` 是 provider 内主键。映射到既有 `HorseProfile` 的顺序 SHALL 为：

1. 已审核 `the_racing_api:horse:hrs_*` identity；
2. 已审核 JRA/JBIS/HKJC/其他官方 crosswalk 同时给出的拉丁名；
3. 严格名 + 完整 DOB + sex + sire + dam 全部一致；
4. 其余只生成 candidate。

日文/中文 seed 必须先从 JRA/JBIS/HKJC 官方记录取得欧字/英文 alias。DOB、sex、sire、dam 或
官方 ID 任一强冲突均阻断 merge。香港裸烙号不能作为跨年代全局 ID；优先 full HorseId。

同一 canonical horse 可以保留多个 provider ID 和多语言 alias；合并不得删除原始外部记录。
任何已合并身份必须有可审计 split/reject 结论。

### Requirement: 网络采集必须受预算、缓存和恢复合同约束

真实请求仅允许 `api.theracingapi.com` 的受审路径。默认全局速率不高于 `4 req/s`，最小间隔
`250ms`；不能为不同 endpoint、进程或 race-live/backfill 各发一份 5 req/s 额度。所有共享同一
账号凭据的 caller 必须经过同一个账号级预算；若现有链路尚不能共享，则 backfill preflight 必须
证明其他 TRA caller 全部关闭。每个 run 必须有：

- 精确 scope manifest 和 request ceiling；
- 持久化 request ledger，失败请求也计数；
- 原子 checkpoint 与 resume；
- 429 `Retry-After` 或指数退避+jitter；
- 401/403、schema drift、分页不前进、重复页立即 safe-stop；
- raw cache 的 URL/status/fetched_at/body SHA/openapi fingerprint；
- 不含密钥的日志与 artifact。

bulk range 每个成功 page SHALL 在下一请求前原子持久化 response wrapper 与
`range/page/path/SHA/size/URL/skip/total/row_count/range_complete` receipt。safe-stop 后的 resume SHALL 只接受
同一 exact plan、G3 approval、OpenAPI、output/account scope 与完整 cache member set，并要求 fresh exclusive proof；
新 client ceiling SHALL 精确为 batch ceiling 减此前所有 attempt 的实际请求数。resume SHALL 从最后 completed page
的下一 skip 继续，不得重新请求已验证页。最终 batch manifest SHALL 绑定 batch-definition 与 complete checkpoint，
execution receipt SHALL 保存全部 attempts 及累计 request count；任一 identity/count 漂移 SHALL 在网络前失败关闭。

每个 CLI 在读取账号预算、创建 claim/client 或发出首个 GET 前 SHALL 读取受审本地 fingerprint 文件，
重验文件 SHA、source URL、OpenAPI version、full SHA、selected paths/schema names 及其 SHA；artifact 函数在
首个 client call 前 SHALL 再读同一文件，防止 preflight 后替换。search、Pro/Standard、horse results 和
bulk results 的实际响应 SHALL 在决定下一请求前执行 endpoint-specific ID/type/pagination/race/runner 校验。
OpenAPI fingerprint、targeted seed、bulk target manifest/JSONL、targeted seed ledger/batch-definition/checkpoint 与每个 HTTP 200
response SHALL 使用 duplicate-key-free、non-finite-free decoder；即使重算内容 SHA、manifest SHA 或 COMPLETE marker，
多解释 JSON 仍 SHALL 在首个 GET、request cache 或 artifact 发布前失败关闭。
Montjeu N1 未批准 `/openapi.json`，因此本地冻结比对与 live 响应校验不产生额外请求；在线重新抓 schema
必须作为新的 host/path/request scope 单独取得 exact G3。

月度/账号总额度当前公开文档未说明，首次真实 proof 必须从账号 dashboard/响应实测确认，不能把
`5 req/s` 当作无限调用许可。

#### Scenario: proof generator 先于 staging schema 发布

- **WHEN** production 尚未应用新增 TRA `ExternalDataSource` choice 的 migration
- **THEN** exclusive-account proof generator SHALL 只用稳定 source key `the_racing_api` 查询既有 import lock
- **AND** SHALL NOT 创建 lock、staging row 或要求 schema migration
- **AND** proof-only 发布 SHALL NOT 读取 TRA 凭据或调用 TRA endpoint

#### Scenario: runner 与 production 位于不同主机

- **WHEN** TRA credential/one-shot runner 位于本机，而 production runtime 位于服务器
- **THEN** proof generator SHALL 同时验证 role=`runner` 与 role=`production` 的两份 fresh host evidence
- **AND** 两份 evidence SHALL 绑定相同 scope/manifest SHA 且覆盖不同 hostname
- **AND** 任一端存在匹配 process、证据缺失/过期/角色错配时 SHALL NOT 生成 proof
- **AND** production DB/Celery/Redis 检查 SHALL NOT 代替 production host process evidence

### Requirement: 写入必须分层且幂等

流程固定为：

1. network export：只写不可变 cache/artifact；
2. normalize：生成 ExternalRace/Result/Horse/History 的 staging package；
3. identity prepare：生成 bind/create/ambiguous/blocked；
4. reviewed P0 artifact；
5. production dry-run：零业务写；
6. batch apply：精确 SHA、备份、maintenance、事务批次；
7. verifier：scope、身份、字段、履历、重放、公开状态。

网络任务不得直接写 `HorseProfile`。apply 不得联网。新 profile 默认 draft，
`auto_first_publish_enabled=false`。manual locks 和已审核中文/本地官方字段优先。

#### Scenario: 生产 apply 必须处于精确关闭态

- **WHEN** production dry-run 或 commit 准备执行
- **THEN** 默认 SHALL 要求同一 host-local deployment lock 原 token 持续有效，并消费最长 5 分钟的私有
  maintenance preflight
- **AND** preflight SHALL 精确绑定 artifact/package/release、apply plan/source batch/region/ordinal、
  revision/image、database/migration 与 lock metadata
- **AND** Beat、赛事专用 worker、赛事写开关、active import/claim 与 `celery/race_sync_v2` 任一未关闭时
  SHALL fail closed
- **AND** 普通 web/worker topology 与 Celery idle snapshot SHALL 精确；`race_live` 只允许记录且在复核时
  保持长度不变，不得为取得 preflight 而清理或消费
- **AND** 任一输入路径的最终文件或中间目录为 symlink 时 SHALL 在读取前拒绝

#### Scenario: rolling apply 必须有原子 receipt 与连续序号

- **WHEN** 多个 reviewed source batch 属于同一 production apply plan
- **THEN** ordinal SHALL 按 `apply_plan_id + region` 连续，`source_batch_id` 不得把每个新来源批次重置为 1
- **AND** claim、canonical business writes、completion run、TaskExecutionLog 与 append-only receipt 的终态
  SHALL 由事务和账本共同保护；业务写成功但 receipt/log 失败时 SHALL rollback
- **AND** completed batch 缺 receipt SHALL 视为损坏并停止，exact completed replay SHALL 为零业务写
- **AND** production apply SHALL 使用 database-only 策略，不自动公开页面、不发送 QQ/邮件、不启动或消费
  race-live

#### Scenario: exact reverse 独立且默认关闭

- **WHEN** operator 请求 reverse 已完成的 production apply receipt
- **THEN** `P0_HORSE_PRODUCTION_REVERSE_ENABLED` 默认 SHALL 为 false
- **AND** 启用后仍 SHALL 要求 active superuser、显式确认、完整批次 identity 与 exact state SHA
- **AND** live after-state 漂移或 created row 存在未捕获关联时 SHALL 在任何反向写入前失败关闭
- **AND** reverse receipt SHALL append-only；无法证明精确反向时 SHALL 使用写前 custom-format dump 恢复

### Requirement: 长批次必须可持续收敛

执行按 `region/year/race chunk` 和 `horse rank chunk` 分片。一个 worker 一次只持有短 claim；
批次完成后写 receipt 并释放。重启、部署或限流后从精确 checkpoint 续跑，不重抓已验证 cache。

当前年度从正式赛果出现后滚动补充；单批完成条件不是“队列为空”，而是 target ledger 的每个
批内目标均达到 `resolved/not_held/not_due/superseded/provider_gap/source_gap/identity_review`
中的一个可解释运行终态，且所有 gap 有明细。整个用户目标只有在所有已举行 in-scope target 均
resolved、所有唯一马均完成落表及 verifier 后才完成；provider/source/identity gap 会进入下一来源
或人工批次，不能被算作最终完成。

## 验收标准

1. 四地区目标账本逐年、逐等级、逐 discipline 守恒，爱尔兰不再为零或并入英国。
2. 2000–2020 held G1 与 2021–当前 held G1/G2/G3 均有终态；不得遗漏年份。
3. 每场 resolved 赛事的实际 starters 与来源 total/状态一致，NR 等排除规则通过。
4. 每个 `hrs_*` 只产生一个 provider horse；每个 canonical HorseProfile 的强身份无冲突。
5. 所有可提交 profile 的硬字段有逐字段来源；缺失字段与 blocker 明确，不使用 placeholder。
6. 单马 results 分页 `rows=total`、race_id 无重复，最早/最晚日期有审计；provider complete 与
   official career complete 分开报告。
7. dry-run 对所有候选给出唯一 disposition；apply 前 ambiguous/unreviewed 为零。
8. 每批 apply 后 verifier 为零错误，重放同一 artifact 业务写入为零，新档案未自动公开。
9. 最终报告给出 target、race、participant、unique horse、identity、profile、career 和 gap 的
   分地区/年份统计，不用 HTTP 成功率代替业务完整率。
10. 最终完成时，已举行 target 的 unresolved provider/source/identity gap 为零；当前年未来赛事
    只以 not_due 排除，并在举行后继续滚动纳入。

## 人工门禁

- 用户当前请求构成 G1：允许完成方案、本地测试和本地实现。
- 真实付费 API 扩大调用前，必须提交 host/path/年份/地区/马数/request ceiling/估算时长/输出目录
  的精确 G3 包。
- merge、生产部署和精确生产 batch apply 在完整测试、审查与 manifest 固化后提交 G2/G3；若同一
  G2 包已经逐项包含相同动作，则不重复询问。
