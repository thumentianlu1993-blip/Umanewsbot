# 四地区分级赛参赛马回填测试用例

## A. 目标范围

| ID | 场景 | 预期 |
| --- | --- | --- |
| A01 | 2000–2020 G1 | 纳入 |
| A02 | 2000–2020 G2/G3 | 排除 |
| A03 | 2021–当前年 G1/G2/G3 | 纳入 |
| A04 | Listed/普通赛 | 排除 |
| A05 | 当前年未来赛事 | not_due，不进入 participant 分母 |
| A06 | 当届升级/降级 | 使用当届 grade，不使用当前 series grade |
| A07 | flat 与 jumps | 四地区分级赛均纳入 |
| A08 | not-held/cancelled/superseded | 可解释终态且 target 守恒 |
| A09 | 2015 年末取消、2016 年初补赛 | `edition_year=2015`、实际日期 2016；只有双证据+人工审核可纳入 |
| A10 | 跨年 occurrence 无 override 或日期不绑定 | fail closed |
| A11 | 同名系列只在后续年份出现第二场 | 全部年份统一使用全局消歧 key；早年不得保留短 key |
| A12 | series 算法改变但事实行未变 | 旧 target/audit/proposal SHA 全部失效，必须重建重审 |

## B. 爱尔兰模型与目录

| ID | 场景 | 预期 |
| --- | --- | --- |
| B01 | Pt I—IRE + Curragh | ireland/flat |
| B02 | IRELAND 页眉跨页延续 | 后续同 section 仍为 ireland |
| B03 | IRISH JUMPS | ireland/jumps |
| B04 | IRE Ark-Hat 旧格式 | ireland/jumps，不再 reset 后丢弃 |
| B05 | IRE 后进入 Italy | 上下文清空，不把意大利赛事归入爱尔兰 |
| B06 | GB 后进入 IRE | 两地区分开，stable series key 前缀不同 |
| B07 | declared total/grade count | ireland 独立对账；不一致 fail closed |
| B08 | RacingRegion choices/时区 | ireland + Europe/Dublin |
| B09 | 明确 IRE 旧记录 reclassification | prepare/dry-run/apply 前后守恒 |
| B10 | 仅赛事名含 Irish | 不自动重分类 |
| B11 | Ireland runner recipe | HRI 保留 official source 但位于 blocked；只有 IrishRacing executable |
| B12 | HRI provider 或 HRI URL 被放入 Ireland source fragment | cache/network 前拒绝 |
| B13 | HRI URL 伪标为 IrishRacing，或 request policy 放宽至 HRI host | cache/network 前拒绝 |
| B14 | 六地区 recipe 存在但 Ireland 无 approved source fragment | 1,957 个 target 全部写入 readiness gap；不得标 executable |

## C. TRA HTTP 与 schema

| ID | 场景 | 预期 |
| --- | --- | --- |
| C01 | 非 allowlist host/path | 请求前拒绝 |
| C02 | redirect | 拒绝 |
| C03 | secret/log | Authorization 不出现在异常、ledger、artifact |
| C04 | 401/403 | 不重试，safe-stop |
| C05 | 429 + Retry-After | 持久化 backoff 并占用请求额度 |
| C06 | 429 无 header | 指数退避+jitter |
| C07 | 5xx | 有界重试；超限 safe-stop |
| C08 | HTML/超大 body/坏 JSON | schema error |
| C09 | 本地冻结 OpenAPI fingerprint 文件/SHA/selected contract/schema 漂移 | 预算、claim、client 和首个请求前阻断并要求 review |
| C09B | live search/profile/results 响应不符合受审字段、ID、分页或 race/runner 合同 | 下一请求前 safe-stop，不把未知 schema 写入 artifact |
| C09C | 需要在线重新抓 `/openapi.json` | 未取得该新增 path 的 exact G3 前不得借 Montjeu N1 调用 |
| C10 | Pro 404 | 只此情况回退 Standard |
| C11 | Pro 500 | 不伪装成 Standard fallback |
| C12 | 两个 export 进程共用 exclusive state | 账号级相邻 request slot 仍不小于 250ms |
| C13 | proof-only 代码运行在 migration 0077 前的 production schema | 使用稳定 `the_racing_api` 字符串只读查锁，不依赖新 TextChoices |
| C14 | management command 成功 | stdout 只含 status/scope/valid-until/proof SHA/零写摘要，不含 credential 或原始 evidence |
| C15 | Compose 验证需要本地 `.env` | 只使用临时空文件做 `config --quiet`，验证后删除，不读取或复制真实 secret |
| C16 | runner 与 production 位于不同 host | 两份 v2 evidence 角色、scope、SHA、freshness 都通过才生成 proof |
| C17 | 两份 evidence hostname 相同或角色互换 | fail closed，不把重复证据当双主机覆盖 |
| C18 | 批次 G3 批准后换用另一 fingerprint path/SHA，或 resume definition 中 fingerprint 漂移 | claim/resume/completion 前 fail closed，旧 approval 不复用 |
| C19 | reserve 后进程崩溃 | attempt 已计入持久 request ceiling，不返还 |
| C20 | concurrent scope/credential alias 漂移 | 请求前 safe-stop |
| C21 | 系统时钟回退或 state/lock symlink | 请求前 safe-stop |
| C22 | shared_db 既有 interval=1000ms | backfill 不降为 250ms，按 1000ms 执行 |
| C23 | 429 Retry-After | 推进账号共享 next_allowed_at，其他进程也等待 |

## D. 分页与缓存

| ID | 场景 | 预期 |
| --- | --- | --- |
| D01 | limit=100, total=230 | skip 0/100/200，累计 230 |
| D02 | 中间页少于 limit 但未到 total | 按 returned_count 推进 |
| D03 | skip < total 返回空页 | fail closed |
| D04 | page hash 重复 | pagination_stalled |
| D05 | total 倒退或 query echo 漂移 | fail closed |
| D06 | 同 race_id 同 payload | 全局去重 |
| D07 | 同 race_id 不同 payload | 生成 revision/conflict，不静默覆盖 |
| D08 | cache 文件被改/换 symlink | resume 拒绝 |
| D09 | 已验证 cache resume | 零网络复用 |
| D10 | COMPLETE marker 缺失 | 下游不得消费 |

## E. 赛事匹配与实际参赛

| ID | 场景 | 预期 |
| --- | --- | --- |
| E01 | race_id 已审核绑定 | 精确复用 |
| E02 | 同日同场同 grade 唯一 alias 命中 | 生成候选后可自动绑定 |
| E03 | 同日两个相似赛事 | ambiguous，不取第一条 |
| E04 | grade/discipline 冲突 | blocked |
| E05 | 数字名次/同着 | 实际起跑保留 |
| E06 | PU/F/UR/DNF/DSQ | 实际起跑保留并规范状态 |
| E07 | NR/scratched/withdrawn | 排除 |
| E08 | 未知非空 position/status | unresolved，阻断该行 |
| E09 | 结果 rows 只含冠军 | participant completeness 不通过 |
| E10 | archived full result 含 1–7 + PU | 8 匹均为 actual starters；PU 保留 |
| E11 | 原 racecard 声明 11 匹、补赛结果 8 匹 | 只以补赛结果 8 匹为参赛分母 |
| E12 | 多匹目标马带回同一赛事 | race payload 去重且不递归扩 scope |
| E13 | target 只有 ExternalRace staging | 不算正式赛事落表完成 |
| E14 | reviewed historical bridge | RaceEvent/Runner/Result receipt 通过后才推进 |
| E15 | 2025 finished target | 使用 graded_horse_backfill layer，可 dry-run/receipt/verify |
| E16 | 2026-07-16 至 as_of_date target | 新 layer接受；旧 current_year_due 合同保持拒绝 |
| E17 | local_date 晚于 manifest as_of_date | bridge/package 阻断 |
| E18 | TRA licensed_api host/provider/response hash 漂移 | bridge/package 阻断 |
| E19 | TOBA 3,941 个 physical rows 含 1 个重复 identity | 保存 3,941 physical / 3,940 unique，不创建重复 occurrence |
| E20 | TOBA 自动绑定 source/target | 从 review candidate pool 排除，避免审核把已占用 identity 重新分配 |
| E21 | source reused 同一 identity 对两个 target | source 侧合并为一个 review item，target 侧保留两项，approval 前不得绑定 |
| E22 | US jumps target 与 TOBA flat history 同窗口 | 标 `unsupported_by_toba_flat_history`，不计入 TOBA unmatched |
| E23 | review candidate 排名第一 | `candidate_rank_is_decision=false`，不能直接进入 occurrence/runner 执行 |
| E24 | 官方赛历日期晚于冻结 as-of date | 生成 `not_due` non-held row，不进入 unresolved execution blocker |
| E25 | 官方赛历日期已过但无结果/取消证据 | 保持 `past_schedule_needs_result`，不得生成 held/non-held 终态 |
| E26 | calendar audit as-of、target SHA 或 source evidence 漂移 | non-held adapter 请求前失败关闭 |
| E27 | France Galop official 与 ZEturf reviewed row 指向同 target/date | 官方行成为唯一 occurrence，第三方行保留为 corroborating reference |
| E28 | 同 target/date 存在两个同级最高 authority rows | fail closed，不按输入顺序选择 |
| E29 | target 已全 accounted，但任一 proposal 未批准或 member SHA 漂移 | 未批准时 `needs_input_approval/PREPARED`；漂移时 fail closed |
| E30 | publisher 收到错误 decision SHA、自批声明、无时区时间或 output drift | 输出目录保持不存在；只有 exact independent decision 可发布 APPROVED |
| E31 | Sporting Life 结果页含数字名次、PU/F/UR 和 non-runner | 数字名次及 PU/F/UR 纳入；non-runner 排除 |
| E32 | ZEturf runner table 含未列 arrival runner 与 `(NP)` | 前者保留为 actual starter/result-unclassified；NP 排除 |
| E33 | semantic runner status 为 unknown | 整场 fail closed，不猜测是否出赛 |
| E34 | France Galop official starter 行名次为 `ARR/tbé/–/J/unknown` | 全部保留 actual start；可确认状态规范化，其余只标 result-unclassified |
| E35 | 同一 exact horse name 出现在多个 target | 保留多个 starter occurrence rows，provider ID 前不合并 |
| E36 | source cache path/size/SHA 或 Wayback approval output 漂移 | census 构建失败，输出不得成为 PREPARED |
| E37 | 350-target census 全量重放 | 3,192 slots、94 withdrawals、350 summaries 守恒且逐字节一致 |

## F. targeted_horse

| ID | 场景 | 预期 |
| --- | --- | --- |
| F01 | search 返回 exact 与前缀相似马 | 不取第一条 |
| F02 | 同名、不同 DOB/父母 | 强冲突，保持多候选 |
| F03 | seed 只有名字且无赛事名次关系 | unresolved，不自动关联 |
| F04 | 唯一 name/country/DOB/sex/sire/dam | identity_verified |
| F05 | horse results 跨越 12 个月 | 全分页接受 |
| F06 | Montjeu fixture 含 1999 Arc | reconciled |
| F07 | Montjeu profile 成功但 1999 Arc 缺失 | provider_partial |
| F08 | anchor horse results 唯一匹配 2000 race | 恢复整场 runners |
| F09 | anchor results 有两个相似 race | race_match_ambiguous |
| F10 | 日文/中文 seed 无官方拉丁 alias | 阻断，不机器音译确认 |
| F11 | 受审来源只有冠军名+唯一赛事；仅一个 exact-name candidate 在该场第 1 | 以 occurrence 强身份绑定 |
| F12 | 两个 exact-name candidate 均满足同一 occurrence | search_ambiguous，不取第一条 |
| F13 | 一场目标赛事含冠军和其他实际出赛马 | 全部 `hrs_*` 进入稳定 ID 总账 |
| F14 | 同一 `hrs_*` 出现在多场目标赛事 | 只生成一个补全 seed，保留全部 occurrence |
| F15 | 稳定 ID 补全 | 只调用 profile/results，不调用 search |
| F16 | 稳定 ID career 缺任一目标 occurrence | safe-stop，不宣称完整 |
| F17 | 目标赛有 NR/withdrawn 或未知状态 | NR 排除；未知阻断总账 |
| F18 | career 的其他赛事出现新同场马 | 只保存 observation，不递归补全其档案 |
| F19 | 外部冠军索引 SHA 或 COMPLETE target SHA 漂移 | 提案生成前失败，零输出 |
| F20 | 冻结页面、request ledger、winner reference 任一漂移 | 拒绝生成 seed candidate |
| F21 | 同一冻结结果被索引到两个 target | 拒绝复用；不得制造两个 occurrence anchor |
| F22 | PREPARED 外部冠军提案没有独立决定 | 不发布 COMPLETE seed ledger，不得进入 TRA batch plan |
| F23 | 独立决定绑定 exact proposal/output SHA | 逐字节发布 COMPLETE seed ledger；后续 batch plan 仍为 PROPOSED_NOT_APPROVED |
| F24 | 350 held target 对回既有 313 COMPLETE seed | 311 条 winner 一致时逐字复用；2 条与唯一官方 winner 冲突时进入显式替换审核 |
| F25 | 剩余或冲突的 France Galop official occurrence 有唯一冠军 | 生成 37 新增 + 2 替换 PREPARED candidate，不直接进入网络批次 |
| F26 | 同名冠军出现在两个 target | 身份确认前保留两条 occurrence seed，不按名称预合并 |
| F27 | 扩展批准 decision 漏时区、自批或 output SHA 漂移 | 不生成 COMPLETE seed ledger |
| F28 | exact independent decision | 发布 350 条 COMPLETE seed；新的 batch plan 仍需独立 G3 |
| F29 | 350 winner seed 映射回 held census target | 350/350 唯一守恒；缺 seed、多 target 或 combined drift 均失败 |
| F30 | 同 target 内 source/TRA 名称去国别后各唯一 | 只生成 `requires_review` binding candidate，不直接批准 identity |
| F31 | 同 target 同名两匹或 source/TRA 任一侧名称未匹配 | 写 review item，reconciliation 不 complete |
| F32 | TRA actual-starter count 与 source census 不同 | target count mismatch 显式保存，不以较小一侧为准 |
| F33 | TRA occurrence 日期/地区/等级/discipline 漂移 | fail closed |
| F34 | stable ledger 含 NR/unknown 或同一 `hrs_*` 在一场重复 | fail closed，不生成 proposal |
| F35 | reconciliation 只提供 PREPARED 350-seed proposal，没有独立批准后的 COMPLETE seed artifact | 请求前拒绝，不消费未批准 39 条新增/替换 seed |
| F36 | COMPLETE seed 的 decision/proposal/output/seed set 任一漂移 | fail closed，不接受“同 seed ID”替代批准链 |
| F37 | reconciliation 仍有任一 review/count/source/TRA gap | 独立批准发布器拒绝生成 COMPLETE |
| F38 | 零 gap proposal 的输入或 output SHA 无法确定性重放 | 独立批准发布器拒绝，0 网络、0 DB 写 |
| F39 | 批次输入为已批准的稳定 `hrs_*` ledger | `search_requests_per_seed=0`，G3 endpoint scope 不含 `horse_search` |
| F40 | 旧 winner-name batch plan 没有 `search_requests_per_seed` | 向后兼容并保留 `horse_search`；非法负数/布尔/字符串失败关闭 |
| F41 | stable-ID 批次使用默认上限 | 每马最多 201 results pages + 2 profile + 4 parent profile GET = 207；每批最多 5 马/1,035 GET |
| F42 | stable-ID plan 与 approved reconciliation 的 stable manifest、decision 或 horse-ID set 漂移 | 计划生成前失败，不形成 G3 proposal |
| F43 | pre-2005 v2 seed 有精确日期 | 日期成为硬过滤；其余结构化赛事字段仍全部核对 |
| F44 | pre-2005 v2 seed 无日期但 year/name/course/grade/discipline/position 唯一 | 可恢复唯一 occurrence；不得降级为名称单键 |
| F45 | date-optional v2 seed 缺赛事名、马场、等级或 discipline | batch plan 与首个请求前 fail closed |
| F46 | date-optional v2 seed 同年匹配两个 occurrence，或两个 exact-name horse 均命中 | `search_ambiguous`，不选择第一项 |
| F47 | PREPARED v2 proposal 无独立 source-anchor decision | runner 不接受 proposal schema，不生成可执行 ledger |
| F48 | source-anchor decision exact-SHA 且 scope 正确 | 只发布 `targeted-horse-seed.v2 / COMPLETE`；network/database 仍未批准 |
| F49 | readiness target 被分类为 not-held/cancelled correction | 不生成 winner seed；写入独立 correction proposal |
| F50 | correction decision 漂移、自批、scope 错误或 output SHA 漂移 | 不发布 approved correction；正确批准后仍 `database_apply_approved=false` |
| F51 | correction 没有 row-level URL/page SHA，但绑定可重放的 source proposal manifest + candidate-row SHA | 允许进入独立审核；缺任一上游 SHA 或无法重放时 fail closed |
| F52 | scoped held reconciliation 只引用 stable ledger 的 exact held source seed | 只选择对应 target；所选 target 内 source/TRA 仍完整守恒 |
| F53 | scoped stable source seed 不在 approved held map | 请求前失败，不把 external seed 混入 held approval |
| F54 | scoped proposal 与 publisher 的 scope、source seed 或 target set 漂移 | 不发布 COMPLETE reconciliation approval |
| F55 | held COMPLETE 与 external single-race COMPLETE 覆盖不同 occurrence | canonical key 并集精确覆盖 stable ledger，可生成 planning-only coverage |
| F56 | mixed-source components 覆盖同一 occurrence 两次 | overlap fail closed，不静默选择 authority |
| F57 | mixed-source union 缺 occurrence、horse ID 或 component SHA 漂移 | gap/drift fail closed，不生成 stable-ID plan |
| F58 | planning-only coverage 生成 stable-ID plan | `search_requests_per_seed=0`；coverage 不授权 network/database |
| F59 | exact next G3 执行只读 preflight | 返回 `ready_for_fresh_exclusive_proof`；不读 proof/凭据、不改 ledger/lock、不创建 output/budget |
| F60 | preflight 的 request ceiling、路径、参数、SHA 或 next ordinal 漂移 | fresh proof 前 fail closed，0 claim / 0 network / 0 DB write |
| F61 | bulk range next G3 只读 preflight | 精确返回 target/date-range/request ceiling 与 `bulk_results`；ledger/lock/output/budget 不变 |
| F62 | bulk preflight 的 output/budget/account/OpenAPI 或 next scope 漂移 | proof 前 fail closed，不创建 claim 或联网状态 |
| F63 | selection v2 exact root+SHA 驱动 selected preflight | 单命令返回 `ready_for_event_release_and_fresh_proof`，ledger/lock/output/budget 不变 |
| F64 | selection SHA/marker、G3 projection 或现场 ledger/lock 漂移 | proof 前 fail closed，不切换到 alternative scope |
| F65 | selection JSON 重复键或布尔冒充 request ceiling/数量 | 严格解析拒绝，不调用底层 preflight |
| F66 | selected batch 是账本最新 COMPLETE、active=null 且 materialization 全量精确 | 生成 `PREPARED_NOT_AUTHORIZED` 后处理计划，0 network/DB |
| F67 | ledger active/已有后续 completed，或 batch/materialization/seed/horse/run SHA 漂移 | fail closed，不生成计划或猜测旧 selected batch |
| F68 | 后处理计划列出 staging apply 与 module review handoff | apply authority 保持 false；candidate 实际生成前 SHA 必须为 required sentinel，不能预批准 |
| F69 | exact materialization 执行 batch dry-run | 全部单马 run 先验证，返回逐项与汇总计数，database writes=0 |
| F70 | batch apply 的第二个 run 异常 | 单一外层事务回滚本批第一 run 的 horse/race/result/history/receipt 写入 |
| F71 | 完整 batch 已有成功单马 receipts 后重放 | 每个 run 返回 replayed、database writes=0；不创建 canonical identity |
| F72 | staged materialization 全体候选 review-required/zero-blocker | 原子发布 candidate batch；exact manifest 可直接驱动 module `prepare-batch` |
| F73 | candidate batch 任一马有日港 crosswalk/字段/evidence blocker | 整批 `PREPARED_BLOCKED`，不得跳过该马进入 module review |
| F74 | candidate batch member bytes、path、status、source run SHA 或成员集合漂移 | loader fail closed，不生成 module proposal |
| F75 | 同一 candidate batch 出现重复 provider `hrs_*` | 输出前拒绝；必须先按 stable ID 去重 |
| F76 | completion audit 接收 exact candidate batch + 同成员 identity/module proposal | 逐马守恒并输出 `AUDITED_INCOMPLETE`，保留 batch/source SHA |
| F77 | completion audit 的 candidate batch 有额外文件、symlink 或 member/source-run/status/SHA 漂移 | 输出前 fail closed |
| F78 | completion audit 同时收到 candidate batch 和逐文件 candidate 参数 | 拒绝混用，不生成审计 artifact |
| F79 | identity review `--prepare-batch` 接收 exact review-ready candidate batch | 生成同成员 `PROPOSED_NOT_APPROVED` identity proposal，0 DB write |
| F80 | identity review batch 模式同时收到 individual candidate 参数 | fail closed，不生成 proposal |
| F81 | completion audit 输入任意层含重复 JSON key | 严格解析拒绝，不生成审计 artifact |
| F82 | completion audit 输入含 `NaN`、`Infinity` 等非有限数 | 严格解析拒绝，不生成审计 artifact |
| F83 | COMPLETE bulk run 含唯一 target mapping、2 actual starters 与 1 NR | 生成 2 个 stable `hrs_*` seeds；NR 不进入 ledger |
| F84 | bulk run plan/cache/normalized/member set 或 manifest SHA 漂移 | stable ledger 输出前 fail closed |
| F85 | bulk stable occurrence 保存 target/run/race/runner provenance | 每条 occurrence 可回绑 exact provider-native bulk run |
| F86 | merged stable ledger 由多个 bulk/held/external source 组成 | coverage components 的 occurrence union 必须无 overlap/gap |
| F87 | 尝试从单个 bulk ledger 绕过全局 merge/coverage 直接 enrichment | 无此正常入口；planner 只接受 exact complete coverage |
| F88 | execution ledger 的 COMPLETE receipt 缺 stable child、存在额外 child，或 bulk/stable participant 绑定漂移 | 只读 frontier 返回最早 postprocess 或 fail closed；仅 frozen plan 全批次一一齐套且 active=null 才给全局 merge inputs |
| F89 | targeted COMPLETE 缺 full materialization/stable child，或 parent/member/actual-starter occurrence 漂移 | 只返回最早 materialize/build argv 或 fail closed；仅 65/65 两段齐套且 active=null 才给分区 merge inputs |
| F90 | pre-2005 targeted materialization 与 source stable/merged occurrence 精确一致 | 生成 `provider_native_targeted_materialization` coverage；source stable 非 lineage、extra member 或 binding count 漂移均拒绝 planning |
| F91 | bulk frozen-plan 全批次与 pre-2005 targeted 65/65 partition frontier 均 ready | 仅输出 `N_bulk+65` ledger exact merge argv；13 马 pilot source 或任一重复 source 不得进入最终 occurrence merge |
| F92 | merged v2 stable manifest 精确绑定全部 frontier source root/SHA | 输出 `N_bulk` bulk-run + 65 targeted-materialization coverage argv；source 缺/多/漂移或 pilot component 阻断 |
| F93 | exact `N_bulk+65` component coverage 与 merged occurrences/unique `hrs_*` 全部守恒 | 只输出 zero-search enrichment planner argv；pilot/extra/missing component、coverage 或参数漂移均阻断 |
| F94 | global enrichment execution 为 0 COMPLETE，四个 postprocess parents 均 absent | 返回 waiting，0 network/DB，不创建 parent 或修改 ledger |
| F95 | materialization/candidate/identity/module children 精确形成 COMPLETE 前缀 | 逐批守恒 source batch/run 与唯一 `hrs_*`；跳批/orphan/source drift 在 proposal 命令前阻断 |
| F96 | exact merged stable ledger 的 `hrs_*` 缺 canonical identity | 仍生成只读 inventory blocker，network/DB=0，completion=false |
| F97 | 同一 profile 有较早已漂移 receipt 与较新 live receipt | 选择最后未 reverse receipt，数据库 inventory 可通过；不把旧 receipt 当最终状态 |
| F98 | 最后未 reverse receipt 的 after-state 已漂移 | `production_receipt.live_state_drift` 硬阻断，public target 不具 fetch eligibility |
| F99 | 两个 provider `hrs_*` verified identity 指向同一 profile | 两行同时标 duplicate-profile blocker，不按顺序静默通过第一行 |
| F100 | merged stable root 有 extra member，或 audited-at 非 ISO-8601 | 查询/输出前 fail closed，不生成可信 inventory |
| F101 | verified identity 对应的 identity review receipt 缺失、reversed 或 after-state 漂移 | canonical inventory 硬阻断，不用 verified 行单独冒充审核完成 |
| F102 | complete inventory 含 21 条履历，生成公开页验收计划 | 精确生成 2 个 URL；第一页无 query、第二页只允许 `records_page=2`，页面履历切片为 20+1，计划阶段 network/DB=0 |
| F103 | injected fetcher 返回两页完整 horse page 机器合同并合并 chunk | chunk 保存每页原始 HTML/body SHA；零联网 merge 重放通过并输出 `COMPLETE_READ_ONLY`，final audit 前 `completion_achieved=false` |
| F104 | 页面 profile/page/count、字段、标题、主胜鞍或履历 ID/顺序任一漂移 | 生成 bound blocker 与 `VERIFIED_INCOMPLETE`，HTTP 200 不得单独升级为通过 |
| F105 | inventory/plan 有 extra member、marker/SHA/count/path 或 URL query 漂移 | 发请求前 fail closed，不接受 prefix URL 或未固定 query |
| F106 | 命令执行未同时提供 `--allow-network` 与 `RACING_API_PUBLIC_VERIFY_NETWORK_ENABLED=true` | 在读取 plan 和发请求前拒绝；prepare 模式永不联网 |
| F107 | public horse detail 的 21 条履历访问第 2 页 | `<main>` 暴露 exact profile/count/page/pages，唯一 record row 暴露 exact DB record ID 与 canonical race key |
| F108 | 单次 execute 请求范围超过 50 行 | 调用 fetcher 前拒绝，避免长任务 HTML 全量驻留内存或中断后全部丢失 |
| F109 | chunk parent 缺首段、中间有 gap/overlap、含额外成员或 response SHA 漂移 | merge fail closed；只有 1..request_count exact coverage 才生成最终 public verification artifact |
| F110 | exact candidate batch、identity proposal/approval、module proposal/approval 覆盖一个全局 stable `hrs_*` 集合 | 逐 child 重放后生成 `COMPLETE` review aggregate；network/DB=0，仍不授予 apply 权限 |
| F111 | 任一 approval/proposal 多出成员、SHA/marker/candidate set/module review 漂移，或跨批重复/缺失 `hrs_*` | aggregate producer/loader fail closed，不接受人工汇总行或部分集合 |
| F112 | complete review aggregate、live canonical inventory 与 complete public verifier 的 provider 集合及 inventory binding 完全相等 | 逐马 identity/module approval lineage 相等后唯一生成 `AUDITED_COMPLETE / completion_achieved=true` |
| F113 | identity approval artifact 或 module approval manifest 与对应 live receipt 不一致 | final audit safe-stop，输出目录不存在；不能用 HTTP 200、inventory complete 或 review aggregate 单项替代 |
| F114 | 三方集合一致但 stable ledger 只含 pilot/少于 frozen-plan `N_bulk+65` 个 authoritative source ledgers | inventory/review aggregate 在最前端拒绝；不能用较小分母自洽地产生最终完成 |
| F115 | global enrichment execution 全部 COMPLETE/inactive，六类 postprocess parent child set 精确等于计划批次 | 自动以 marker-last 发布 `batch-bindings.jsonl + manifest.json + COMPLETE`；network/DB=0，不需人工逐行接线，既有 output 不覆盖 |
| F116 | execution 未完成/active，任一 parent 缺 batch 或含 extra pilot | binding producer safe-stop，output absent；不能把 proposal 前缀冒充全量审批 |
| F117 | identity/module approval 的 marker/member/proposal SHA/decision/horse set 漂移 | binding producer 在发布前拒绝；已发布 wrapper 的 extra member 或 manifest/SHA 漂移在重载时拒绝 |
| F118 | aggregate 命令使用 automatic binding artifact | root+manifest SHA 成对输入并严格重载；raw JSONL+SHA 仅兼容且与 artifact 模式互斥 |
| F119 | global execution/proposal 仍为零状态 | approval frontier 返回 `review_proposals_incomplete`，0 approval/output/authority，不创建 future parents |
| F120 | 前一批 identity/module proposal 已验证、后一批仍等待 materialization/network | 前一批立即得到 exact identity review handoff；不要求等待全量 proposal，也不自动 publish |
| F121 | identity approval 已 exact、module approval 缺失，或存在 orphan/跳批/loader drift | 返回 exact module review handoff；非法 approval child 或 artifact 漂移失败关闭且不生成 binding |
| F122 | 全部 planned batches 的 identity/module approvals 均 exact | 返回唯一 automatic binding argv，仅授权本地 immutable artifact、network/DB=0；production apply 仍为 false |
| F123 | identity proposal 同时含 verified ID、official/local crosswalk、strong biodata、observed ID、create-new 与 ambiguous rows | 逐行进入对应 cohort，counts 守恒；全部 `manual_review_required=true / automatic_approval_allowed=false` |
| F124 | decision template action/profile/row binding 与 proposal 推荐值漂移 | cohort classifier 失败关闭；不得用修改后的 template 批量批准 |
| F125 | module review row 的推荐摘要被修改，rows/manifest/marker SHA 同时重算 | publish 逐行重放 exact candidate 并重建 manifest，approval output 创建前失败关闭 |
| F126 | module proposal manifest 含 duplicate key 或 `NaN`，并重算 manifest/marker SHA | 严格 JSON loader 在 publish 前拒绝，不生成 approval |
| F127 | identity reviewer decisions 含 `NaN` 且重算 decisions SHA | identity approval 严格解析失败，不生成 approval artifact |
| F128 | targeted batch/run/materialization/normalized artifact 含 duplicate key 或 `NaN`，并重算 member/manifest/marker SHA | materializer/staging 在 dry-run 与 DB transaction 前严格拒绝 |
| F129 | HTTP 200 provider response 含 duplicate key 或 `NaN` | network client 在返回 payload、写 cache 或生成 artifact 前失败关闭 |
| F130 | OpenAPI fingerprint 或单马 targeted seed 含 `NaN/Infinity` 且内容 SHA 已重算 | reviewed input loader 拒绝，不创建 network client 或发出 GET |
| F131 | bulk target manifest 含重复 key，或 target JSONL 含非有限值，并同步重算 manifest/ledger/COMPLETE SHA | `_load_targets` 在 bulk 请求前失败关闭 |
| F132 | targeted batch seed ledger 或本地 batch-definition/checkpoint JSON 含重复 key 或非有限值 | batch loader 在首个 seed 请求或 resume 前失败关闭 |
| F133 | credential/entitlement diagnostic 的 HTTP 200 body 含嵌套重复 key 或 `NaN` | 只生成 `FAILED / invalid_json`，不得生成 COMPLETE 或声称凭据可用 |
| F134 | target catalog as-of 仍为 2026-08-29，calendar/coverage/occurrence/bulk 执行 as-of 推进到 2026-08-31 | 同一自然年允许重建下游 artifact，target SHA 与 12,048 分母不变 |
| F135 | 执行 as-of 早于 target catalog、跨自然年，或 non-held proposal as-of 与 occurrence 不同 | 请求/DB 前失败关闭，不生成 COMPLETE |
| F136 | 旧 `not_due.local_date` 已不晚于新执行 as-of | occurrence compiler 拒绝陈旧 row；coverage/due 分母必须重新计算 |
| F137 | bulk range 第 1 页成功、第 2 页 transport 失败，随后显式 resume | checkpoint 保存第 1 页和 2 次已消耗请求；新 client ceiling 为剩余额度，只请求下一 skip，最终累计 receipt 守恒 |
| F138 | resume 前 batch-definition、cache bytes/member set、checkpoint 或 prior request count 漂移 | 首个新 GET 前失败关闭，旧 cache/attempt 不删除、不重取 |
| F139 | execution ledger safe-stop 后使用过期 proof 或 fresh proof 恢复 | 过期 proof 拒绝；fresh proof + 原 exact approval 生成新 claim，最终 receipt 保留 `[safe_stopped, complete]` 两次 attempt 与累计请求 |
| F140 | 官方 OpenAPI full SHA 或 selected path/schema 漂移，standard schema 从 `HorseStandard` 改为 `Horse` | deterministic capture 保存 full/selected SHA、operation plan/rate；review artifact 精确绑定本地 fingerprint，旧 fingerprint 在 network client 前失效 |
| F141 | bulk planner 输入一个完整年份，provider 合同要求一次查询一个日期 | readiness 生成 365/366 个 `start=end` ranges；batch 可聚合但 runner 逐日请求，禁止年度或多日 query |
| F142 | 单个日分区异常超过分页上限，或 15 分钟 proof 在批次中到期 | 立即 safe-stop，保存逐页 checkpoint/累计请求；不扩大 ceiling，以 fresh proof 从下一页 resume |

## G. Profile 与二代血统

| ID | 场景 | 预期 |
| --- | --- | --- |
| G01 | Horse Pro 完整 | DOB/sex/colour/breeder/父母入 normalized staging |
| G02 | Standard fallback | 保留缺失字段与 pro_unavailable |
| G03 | sire/dam parent profile | 得到父父/父母/母父/母母 |
| G04 | parent profile 不存在 | pedigree gap，不同名猜测 |
| G05 | 多匹马共用父母 | parent profile 只请求一次 |
| G06 | parent 指向循环/异常前缀 | 最大深度阻断 |
| G07 | latest trainer/owner observation | 带 as_of 生成 candidate |
| G08 | 历史 observation 晚于/早于冲突 | 不把旧关系冒充当前 |
| G09 | intro 缺失 | 不阻断数据导入 |
| G10 | rating/comment/odds | 不进入 HorseProfile 权威字段 |
| G11 | normalized parent 与同包 Pro/Standard response payload SHA 一致 | parent response 可进入候选 evidence |
| G12 | 未声明 parent endpoint 或 normalized/matrix/response parent hash 漂移 | 候选失败关闭 |

## H. 身份与跨语言去重

| ID | 场景 | 预期 |
| --- | --- | --- |
| H01 | 同 hrs_* 多次参赛 | 一个 ExternalHorse |
| H02 | 同名两个 hrs_* | 保持两马 |
| H03 | 已审核 TRA identity | 自动绑定既有 profile |
| H04 | JRA/JBIS 官方欧字 crosswalk | 日文/英文记录绑定同 profile |
| H05 | HKJC full HorseId 中英 crosswalk | 香港/海外记录绑定同 profile |
| H06 | 裸香港烙号跨年代重复 | 不自动合并 |
| H07 | DOB+sex+sire+dam 全一致 | strong candidate |
| H08 | 任一强字段冲突 | blocked_conflict |
| H09 | 仅 loose name 相似 | review candidate |
| H10 | 已绑定错误 identity 被 reject/split | 原始 provider rows 保留、canonical 关系可撤销 |
| H11 | reviewed bind_existing 首次 apply | 唯一 verified identity + canonical alias + receipt |
| H12 | reviewed bind_existing replay | 业务写入为 0 |
| H13 | provider ID 已绑定其他 profile | 无显式 reject/rebind 时整批 rollback |
| H14 | reverse ledger after-state 未漂移 | 精确恢复 identity/name variant before-state |
| H15 | reverse 前发生后续合法修改 | 拒绝 reverse，不覆盖新状态 |
| H16 | canonical profile 只有 HorseNameVariant 命中海外英文名 | 进入 name-match snapshot；variant 漂移使旧 snapshot 失效 |
| H17 | census-to-TRA binding 仅凭场内唯一名称候选 | 必须独立 exact-SHA review 后才可成为 provider identity；名称本身不是批准 |
| H18 | 双向 HorseNameVariant 只有 `is_official=true` 或任一 evidence 字段缺失 | 不得直接 bind；回到普通召回/review |
| H19 | verified local namespace 与 evidence authority host 不一致，或 official source 与 profile region 不一致 | 不得升级 official crosswalk |
| H20 | proposal 后 official crosswalk 的 external linkage/有效期/evidence URL/SHA 漂移 | proposal/approval 失效，零 identity 写入 |
| H21 | 一个可信 crosswalk 与指向另一 profile 的未可信 official claim 并存 | blocked_official_crosswalk_conflict，显示全部候选 profile |
| H22 | authority host 正确但 URL horse-record ID 与 verified local key 不同 | claim 标 untrusted，不得 direct bind |
| H23 | production identity census 显式 provider ID scope | provider/external/decision/current identity/official claim/profile snapshot 全部冻结，0 网络/0 DB 写 |
| H24 | census provider ID 缺失/重复/非法、naive 时间或已存在输出目录 | artifact 生成前失败关闭 |
| H25 | 相同 DB snapshot、scope 与 generated-at 重放 | rows 与 manifest SHA 逐字节一致 |

## I. Artifact 与生产边界

| ID | 场景 | 预期 |
| --- | --- | --- |
| I01 | network export | database_writes=0 |
| I02 | artifact 路径逃逸/symlink/extra file | 拒绝 |
| I03 | target/source/tool SHA 漂移 | reviewed decision 失效 |
| I04 | dry-run | 执行 commit 同等校验但业务零写 |
| I05 | apply 联网开关开启 | 仍不得联网 |
| I06 | manual lock/已审中文名 | 不覆盖 |
| I07 | 新 profile | draft 且 auto_first_publish=false |
| I08 | 同 artifact 重放 | create/update=0，全部 noop |
| I09 | 中间 batch 失败 | 后续 ordinal 不运行 |
| I10 | receipt 已完成 batch resume | 不重复写入 |
| I11 | per-horse raw race payload | 内容寻址 cache 一份，history 行只存引用 |
| I12 | 两个 seed 包含同一 race | batch object pool 只有一个 race object，两个引用 |
| I13 | 两 writer 并发发布同 hash | 只保留逐字节一致对象，无临时/部分文件 |
| I14 | GC/retention | 所有 manifest/receipt 活引用对象不删除 |
| I15 | materialized artifact 丢失 response wrapper | P0 candidate 失败关闭，不接受仅 normalized 值 |
| I16 | credential/port/fragment/query 漂移的 TRA response URL | 候选拒绝；search response 仅允许单一非空严格 `name` 或 `q` 参数后忽略 |
| I17 | 输入最终文件为普通文件，但任一中间目录为 symlink | preflight 与 host wrapper 均在读取/执行前拒绝，不允许绕出可信 runtime root |
| I18 | 同名非目标马 results ID 已由同包严格 search response 披露 | 只标 discovery probe 并排除出目标马 source evidence |
| I19 | 非目标 results ID 未由 search 披露，或任意其他未声明 horse endpoint | 候选失败关闭，不把额外响应静默忽略 |
| I20 | identity/module proposal 输入同时含目标 results 查询与安全 parent profile evidence | 所有 URL 先严格校验；只用目标 profile/results 绑定身份与 career coverage |

## J. HorseRaceRecord 与页面

| ID | 场景 | 预期 |
| --- | --- | --- |
| J01 | provider external race ID | canonical key 稳定 |
| J02 | 旧记录唯一自然键命中 | 原地接管 |
| J03 | 多条旧记录同时命中 | ambiguous，停止 |
| J04 | DNF/DSQ | start_status=started，结果状态正确 |
| J05 | duplicate career race | 一条 record |
| J06 | major win | 仅实际获胜且当届 G1/G2/G3 |
| J07 | starts/wins/seconds/thirds/win rate | 从 records 确定性重算 |
| J08 | provider total 与累计 rows 不等 | career incomplete |
| J09 | provider complete 但无官方总数 | authority status 不冒充 verified |
| J10 | 公开状态未批准 | /horses/<id>/ 仍 404 |
| J11 | `1DH` 与 NR 同在 career | `1DH=won/started`；NR=`did_not_start` 且不计 starts |
| J12 | GB/FR/IRE/USA target occurrence 跨 2000/2020/2021/当前窗口进入 module review | target event region/date/grade 与 career record 原样进入 reviewed research/P0 合同 |

## K. PostgreSQL、并发与回滚

| ID | 场景 | 预期 |
| --- | --- | --- |
| K01 | 两 worker 抢同 batch | 只有一个获得 claim |
| K02 | claim 过期后 resume | fencing token 防止旧 worker 提交 |
| K03 | unique identity 并发插入 | 一个成功，一个转为冲突/noop |
| K04 | 单 batch 中途异常 | 整批 rollback |
| K05 | 后一批异常 | 之前 completed receipt 保留可续跑 |
| K06 | reverse ledger | 精确还原该批 before state |
| K07 | pg_dump 尚未结束 | 不得计算最终备份身份或 apply |
| K08 | pg_restore --list 失败 | apply 阻断 |
| K09 | SQLite 聚焦测试 | 基础逻辑通过 |
| K10 | PostgreSQL 集成测试 | 锁、约束、事务、rollback 通过 |
| K11 | production commit 未提供 fresh exact maintenance preflight | 默认配置下请求前拒绝，不允许降级为旧直接 commit |
| K12 | Beat/专用赛事 worker 运行，普通 worker 不唯一，任一赛事写开关开启，或 celery/race_sync_v2 非零 | preflight fail closed；不 claim、不写业务表 |
| K13 | race_live 队列在 proof 与 commit 复核之间变化 | 阻断；只允许记录并保持原长度，绝不为 apply 清理/消费 |
| K14 | 两个 source batch 属于同一 apply plan | region ordinal 在 plan 内连续，第二个 source batch 不得重置为 1 |
| K15 | batch 标 completed 但 receipt 缺失 | 视为账本损坏并停止，不执行 replay 或下一 ordinal |
| K16 | 业务写入成功但 receipt/TaskExecutionLog 任一步失败 | 同一事务整体 rollback；receipt 创建后 ORM update/delete 均拒绝 |
| K17 | reverse 前 after-state 漂移，或删除 created row 会影响未捕获关联 | 整批 reverse 前失败关闭，不覆盖后续合法写入 |
| K18 | exact reverse 未启用开关、缺完整批次/state SHA、缺显式确认或 operator 非 active superuser | 拒绝 reverse；默认配置保持禁用 |
| K19 | completed receipt identity 与 live after-state 完全一致 | replay 为零业务写；随后才允许 claim 下一连续 ordinal |
| K20 | production apply 走数据库专用发布策略 | receipt 事务后不自动公开页面、不发 QQ/邮件、不启动或消费 race-live |

## L. 最终验收

| ID | 场景 | 预期 |
| --- | --- | --- |
| L01 | 每地区/年/grade/discipline | target 数守恒 |
| L02 | participant occurrence | source race totals 对齐 |
| L03 | unique provider horse | hrs_* 唯一 |
| L04 | identity disposition | 每匹恰好一个终态 |
| L05 | profile field matrix | 字段非空/unknown/source 可追溯 |
| L06 | career matrix | provider 与 authority completeness 分开 |
| L07 | gap ledger | 所有 gap 有 target/原因/下一动作 |
| L08 | public page 抽样 | 展示字段、统计、血统、分页履历正确 |
| L09 | 无副作用 | 未自动公开、未发 QQ/邮件、未启动 race-live |
| L10 | final replay | 所有已完成 artifact 重放零写 |
| L11 | 当前批次 provider gap | 可 safe-stop，但整个 change 不能标记 complete |
| L12 | 最终完成 | 已举行 target unresolved gap=0；未来 target 仅 not_due |
| L13 | 唯一精确赛名但 OCR 距离冲突 | 选择精确赛名并保留距离质量问题，不改配相邻赛事 |
| L14 | target/source 均有等级且不一致 | 硬拒绝，不用其他等级来源补位 |
| L15 | 官方赛历只有 scheduled 日期 | 标 past_schedule_needs_result，不生成 actual starters |
| L16 | 官方来源包含范围外 trial | source_unmatched 有因保留，不强制塞入目标 |
| L17 | 当前完成度审计消费冻结 target/coverage/occurrence/starter/candidate/review | exact SHA 与 target/provider/record set 全部守恒后只发布 `INCOMPLETE`，不冒充最终完成 |
| L18 | coverage 缺/多任一 target，或 evidence-state count 漂移 | 失败关闭，输出目录不存在或保持为空 |
| L19 | starter census 的逐 target count、occurrence target 或 provider-ID count 漂移 | 失败关闭，不生成 audit marker |
| L20 | candidate 与 identity/module proposal 的 path/SHA/provider-ID/record count 不守恒 | 失败关闭，不把两个样本计作已批准资料 |

## 测试执行顺序

1. 为爱尔兰 parser、TRA client/schema/pagination、target scope、identity 和 artifact 合同取得 RED。
2. 实现纯函数与离线 fixture，运行研究工具测试。
3. 实现 Django model/service，运行 SQLite 聚焦测试。
4. 运行 migration check、Django check、受影响 stable 测试。
5. 运行真实 PostgreSQL 的并发、事务、rollback、幂等测试。
6. 只在精确 G3 后运行脱敏小样本 TRA proof；真实响应只保存受限 cache，不提交仓库。
7. 全量网络完成后，以冻结 artifact 做生产 dry-run 和 verifier。

## Requirement -> test -> task -> evidence 追踪矩阵

矩阵只证明“合同存在且已有何种证据”，不把 `PREPARED`、测试通过或来源路径误报为数据完成。

| Requirement | 核心测试 | 对应任务 | 当前证据/状态 |
| --- | --- | --- | --- |
| 范围按实际年度和当届等级判断 | A01–A12、L01 | 1：目标总账；8：范围守恒 | reviewed COMPLETE target 12,048 行，R1 当前范围 blocker 已关闭 |
| 四地区独立建模 | B01–B14 | 1：Ireland 与四地区 ledger | Ireland model/parser 与六地区 runner recipe 已实现；readiness 审计确认 HRI blocked、IrishRacing URL missing 1,957/1,957；当前地区数 GB 3,194、IRE 1,957、FR 1,891、USA 5,006 |
| 应到分母独立于 TRA 返回 | A05–A12、F134–F136、L01–L03 | 1：occurrence；7：持续导出 | 2026-09-01 partial ledger：350 held + 109 not_due + 11,589 explicit unaccounted |
| series inventory 与 occurrence 分层 | A08–A12、E01–E28、F134–F136、L13–L16 | 1：held occurrence/官方赛历 | 350 held；3,726 TOBA 待审核；109 not_due；183 past-calendar-gap；7,680 route-only |
| 实际参赛来自正式赛果 | E05–E11、F13–F18、L02 | 3：actual-starter ledger | France 2026 已确认 566 starter slots；其他范围尚未闭合 |
| TRA 双入口与历史单马路径 | C01–D10、F01–F18、F43–F90、F140–F142 | 2–3、7：client、bulk、targeted horse、pre-2005 seed/correction、mixed coverage、next-batch preflight/selection/postprocess/staging/candidate batch | France 2023 stable-ID 5/5、19 GET 已 COMPLETE 并进入 External staging；官方 OpenAPI 已刷新，bulk 已改为 31,656 个单日分区/88 批，等待按 ordinal 持续执行 |
| 单马页字段逐字段评估 | G01–G10、J01–J11、L05–L08 | 5：profile/pedigree/career | 字段矩阵与零写 P0 候选桥已实现；authority review、正式 release 与页面验收未完成 |
| 跨语言身份不得仅按名称合并 | H01–H25、L04 | 4：identity/crosswalk | provider ID + reviewed receipt + read-only production census 已实现；official 布尔标记不能单独授权，authority record ID/namespace/证据与 snapshot 漂移门禁已实现；真实全量 census 尚未在生产执行 |
| 网络预算、缓存与恢复 | C01–D10、F137–F142、I01–I17、K01–K05 | 2、7：预算与批次 | 账号凭据与 France 2023 entitlement 已实证；单日 bulk 计划固定 4 req/s、逐页 checkpoint、proof-expiry safe-stop/resume，完整 88 批仍待执行 |
| 写入分层、幂等、可回滚 | E13–E18、H11–H17、I01–I17、K01–K20 | 3–6：bridge、staging、apply | 本地 maintenance preflight、rolling receipt/replay/reverse 合同已实现；生产 backup/dry-run/apply 未执行 |
| 长批次持续收敛 | K01–K20、L01–L16 | 6–8：批次、持续导出、最终验收 | 仍处来源补齐阶段，`execution_ready=false`，不可宣称完成 |
