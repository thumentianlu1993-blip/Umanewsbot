# 四地区分级赛参赛马与完整资料回填设计

## 设计结论

采用“独立应到总账 + TRA 双入口 + provider staging + 身份审核 + P0 产品层 apply”的分层架构。
现有年度参赛马 collector、历史赛事总账和 P0 reviewed-artifact 均保留；新增代码只补它们之间
缺失的四地区多年编排、爱尔兰模型、TRA 历史导出与产品桥。

    TJCIS/地区目录 caches -> frozen series/year target ledger ----+
    官方 held/not-run/date/result -> occurrence ledger -----------+
                                                                  |
    TRA /results by day -> race/result caches --------------------+
    external anchor seeds -> horse search/results -> recovered race|
                                                                  v
                                          participant occurrence artifact
                                                       |
                                          hrs_* provider horse set
                                                       |
                           Pro/Standard + parent profiles + horse results
                                                       |
                                      normalized staging/review package
                                                       |
                       production identity census -> mapping decisions
                                                       |
                             P0 module review -> dry-run -> batch apply
                                                       |
                                       verifier + public-page read-only QA

## 1. 范围与数据源

### 1.1 目标总账

首选现有 TJCIS 1998–2026 Blue Book caches。扩展
runtime/tools/prepare_tjcis_ics_catalog.py：

- 新增 ireland section 与 stable prefix；
- flat 识别 Pt I—IRE / IRELAND；
- jumps 识别 Pt IV—IRE / IRISH JUMPS / IRELAND JUMPRACES；
- declared total/grade count 为爱尔兰独立分母；
- 继续保留页面上下文隔离、appendix 截断、同页多国家切分和 source conflict 审批。

编译器从完整年度目录中过滤：

- 2000 <= year <= 2020 and grade=G1；
- 2021 <= year <= run_year and grade in G1,G2,G3；
- region in GB/IRE/FR/USA；
- discipline in flat/jumps。

TJCIS 是赛事等级与范围底表，不自动证明实际举行、日期和 runners。逐地区的官方/行业目录只作为
修正或交叉核对：

- GB：BHA Pattern/Jump Pattern；
- IRE：Horse Racing Ireland / Irish Pattern Committee；
- FR：France Galop；
- USA：TOBA/AGSC；
- 无结构化历史入口时保留 TJCIS 证据和 gap，不用搜索摘要直接写库。

target ledger 的 `target_key` 是 series/year 范围键，不是实际场次键。地区结果层必须再生成
occurrence ledger：允许一个 target 在同一年对应多个 held occurrence；每个 occurrence 以地区、
当地日期和官方 result identity（或经过 SHA 固定的官方历史行）区分。TOBA 2022 已存在同一赛事
系列一年举行两次的实例，因此 series/year 或赛事名去重会造成真实漏数。

年度目录解析只产生候选 series 属性；builder 汇总 2000–当前全部年份后必须再运行一次全局消歧，随后
才可计算 `series_key/target_key` 和 source conflict review。全局 key 迁移属于 artifact identity 变化，
即使事实行数不变也会级联失效 audit、alias、occurrence 和 seed。冻结外部网页可通过 source manifest
校验后零网络复制到新 cache root，但不能沿用旧 target binding 或伪造相同 manifest。

target year 表达当届分级身份，不强制等于补赛实际日期年份。跨年 occurrence 默认拒绝；仅当
`cross_year_evidence.v1` 同时绑定原定日期、次年实际日期、取消/延期原因、可信来源缓存 SHA、reviewer
和带时区 reviewed_at 时，允许 `local_date.year=edition_year+1`。同年 occurrence 反而不得携带该 override，
防止把普通赛日或香港马季误标成特殊延期。正式 `RaceEvent.year` 仍取实际日期自然年，series/target
关联使用 `edition_year`。

美国 2000–2024 使用 TOBA official history 作为 held occurrence 分母。`2010+` 多数行带
Equibase result URL，可直接发现赛果；`2000–2009` 行通常只有 date/grade/track/winner/field，
走 winner targeted-horse 路径恢复整场。current annual table 同时保留 `held/scheduled/not_run`，
只有 held 进入 participant scope。英国、爱尔兰和法国沿用 BHA/HRI/France Galop 日期/结果发现，
同样输出统一 occurrence schema；无明确状态的 target 保留 gap，不能默认为未举行。

官方赛历先进入独立 candidate audit，不直接进入 occurrence compiler。匹配顺序为地区/年份/discipline、
canonical 场地、显式等级、受审名称 alias、唯一精确名称、距离质量；目标和来源都有等级时不允许跨等级
回退。唯一精确名称可压过 OCR 距离异常，但异常仍写入质量证据。输出同时守恒
`target candidates + target issues` 与 `source matches + source unmatched`；past schedule 统一停在
`past_schedule_needs_result`，只有后续 result/取消终态才进入 occurrence 层。

当前年度 artifact 采用双日期：target catalog `as_of_date` 固定范围事实，calendar/coverage/occurrence/bulk
`execution_as_of_date` 表达本次重放日期。后者只允许在同一 catalog 年内单调向前，不能早于 catalog。每次推进都重建
下游 SHA；non-held proposal 必须绑定执行日期，且 occurrence compiler 拒绝任何
`disposition=not_due AND local_date <= execution_as_of_date`。因此日期越过赛日时会自动回到结果/取消证据 gap，
不会靠旧 future artifact 缩小应到分母。G3 与 proof 继续绑定完整 plan SHA，不能跨刷新复用。

### 1.2 TRA 数据路径

bulk_results：

- 按 date + region 调 /v1/results?limit=100&skip=N；
- GB=GB、IRE=IRE、FR=FR、USA 使用 North America entitlement；
- 以日期分区，避免大日期范围深 skip；
- 对每个 response 先验 schema，再以 race_id 入 cache；
- 只把与 target ledger 唯一匹配的 G1/G2/G3 race 纳入 scope。

targeted_horse：

- 输入 manifest-bound `targeted-horse-seed.v1|v2` ledger；v1 要求精确日期，v2 只用于 pre-2005
  date-optional anchor；
- search 产生候选集合；
- Pro/Standard 校验姓名、国别、DOB/出生年、sex、sire、dam；
- 若可靠来源只有“马名 + 目标赛事 + 实际名次”，则逐个 exact-name candidate 拉 horse results，
  以唯一 occurrence 作为强身份；v1 使用 date/course/race/grade/position，v2 在日期缺失时使用
  edition year + canonical name/aliases + course/aliases + grade + discipline + position；这不是名称单键；
- 对唯一 horse_id 拉全部 horse results；
- 用 target 的 year、可选 date、course/name aliases、pattern 和 discipline 匹配唯一 race；日期存在时不得放宽，
  日期缺失时同年多解必须失败关闭；
- 适用于单马专题、2000–2004、bulk entitlement gap 和单场恢复。

target_runner_stable_id：

- 消费已完成且 manifest/SHA 锁定的 targeted-horse materialization，或零 gap 的 COMPLETE bulk range run；
- 从每个目标 race 的 `actual_starters` 取得 provider `hrs_*`，跨赛事全局去重；
- bulk 路线须重新加载原 batch plan/target ledger、重算 reconciliation 并守恒 response cache/normalized/member set；
- 每个唯一 `hrs_*` 保存其所有目标 occurrence、源 runner/race payload hash 和上游 batch manifest；
- read-only postprocess frontier 要求每个 COMPLETE execution receipt 恰有一个固定 batch child stable ledger；只有
  冻结 bulk plan 的全部批次齐套且 execution active=null 才给出全局 merge inputs；
- pre-2005 targeted 因 compact output 需先物化；对应 frontier 要求每个 COMPLETE receipt 恰有一个 fixed-child
  full materialization 与一个 stable ledger，65/65 齐套且 inactive 后才给该分区 merge inputs；
- 全部来源 ledger 先跨批 merge，再以 provider-native bulk、provider-native targeted materialization、held/external
  components 证明 occurrence coverage=100%；targeted component 必须回绑 exact materialization 与 merged-lineage stable source；
- 最终 denominator merge 只消费冻结 bulk plan 定义的全部 bulk stable 与 65 个 pre-2005 targeted stable；France/Ireland 13 马 pilot
  occurrence ledgers 因被 bulk 覆盖而排除，避免同一 horse/race/target occurrence 双录；
- coverage build 前独立重验 merged v2 的 source identities 与两个 frontier 完全相等，并由 frontier 生成恰好
  `N_bulk` 个 bulk-run 与 65 个 targeted-materialization authority component 参数；本次按日计划
  `N_bulk=88`，即 153 个 source identities；
- coverage COMPLETE 后再运行只读 plan readiness：复用同一 `N_bulk+65` frontier，精确守恒全部 components、全部
  occurrence 与 unique `hrs_*`，只输出固定 zero-search/5 马批次 planner argv；
- 全量 plan 的 COMPLETE 批次再进入固定 batch-ID child 的四段 postprocess frontier：materialization、candidate、
  identity proposal、module proposal；四层只允许连续前缀，candidate handoff 前重验 source batch/run 与 horse union；
- 直接按稳定 ID 拉 Pro（404 回退 Standard）、全部分页 results 和有界 parent profile，不再 search；
- 每个目标 occurrence 必须在该马 career 中唯一复现且 race payload hash 不变，否则 safe-stop；
- career 中非目标赛事的 runners 只作为赛果 observation，不递归加入 enrichment scope。

外部 winner anchor 在进入 targeted_horse 前增加两层离线边界：

1. `external-winner-anchor-input.v1` JSONL 只列 exact target key、冻结 reference root 与 capture/reference
   SHA；proposal builder 重验 COMPLETE target、单页 request ledger、source payload 和冠军名次，输出 seed 与
   evidence 两份逐行守恒文件，状态固定为 `PREPARED_NOT_EXECUTABLE`。
2. 独立 publisher 重新读取 target、index、capture、seed/evidence，并要求非实现者 decision 同时绑定
   proposal/output SHA。只有通过后才发布现有 batch planner 可读取的
   `targeted-horse-seed-ledger.v1 / COMPLETE`；batch planner 随后仍生成不可执行 G3 提案。

pre-2005 全局 readiness 另增加两个互斥输出边界：

1. winner anchor 先生成 `proposed-targeted-horse-seed.v2`，即使 readiness 已零 unresolved，proposal 仍不可被
   runner 读取；独立 publisher 只在 scope 为
   `SOURCE_ANCHOR_SEED_PUBLICATION_ONLY_NO_NETWORK_OR_DATABASE_WRITE` 的 exact-SHA decision 后发布
   `targeted-horse-seed.v2 / COMPLETE`。精确日期可选，但 edition year、地区、赛事名/alias、马场/alias、等级、
   discipline 和冠军名次必须齐全。
2. not-held/cancelled target 进入 `pre-2005-calendar-correction-proposal.v1`，不生成 seed。独立 publisher 只接受
   `CALENDAR_CORRECTION_PUBLICATION_ONLY_NO_DATABASE_WRITE`，发布后仍保存
   `database_apply_approved=false`；每行至少绑定上游 source proposal manifest 与 candidate-row SHA，来源提供
   row-level URL/page SHA 时继续精确绑定，未提供时由上游 manifest 重放冻结 cache 和候选分类；任何数据库
   修正另走 historical calendar review/apply。

当前冻结分母按 `1,144 = 1,128 winner anchors + 16 calendar corrections + 0 unresolved` 守恒；runner 只可消费
独立批准后的 1,128 seeds，不能把 16 个 correction 当作缺失 seed 或可查询赛事。

Ireland detail 的当前可验证实现只新增 `ireland_irishracing -> irishracing_ireland` 冻结页面离线 parser
与地区 admission。HRI 是优先官方 authority，但当前没有可验证的 HRI HTML fixture/parser，公开自动化访问
也未形成许可结论，因此不能把 HRI 搜索摘要或 403 页面冒充为已接入官方历史结果链。IrishRacing 仍是
`third_party_high_access` fallback，只有受审 source map/cache 才能进入后续 detail package。

runner v2 的 recipe 现显式扩为六地区，并把 Ireland 的 authority 顺序与可执行性分开保存：
`source_chain=[hri, irishracing]`、`official_sources=[hri]`，但
`executable_sources=[irishracing] / blocked_sources=[hri]`。Ireland 的 request policy 只允许 HTTPS
`irishracing.com` / `www.irishracing.com` 的 `/raceresults/` 路径；HRI provider、HRI URL、将 HRI URL
伪标为 IrishRacing，以及把 HRI 改为 executable 都必须在 cache 和网络之前失败关闭。该 recipe 只让
已批准的 IrishRacing direct URL 具备离线 runner 描述能力，不证明任一 target 已有 URL、页面或 occurrence。

2000–2004 的赛事恢复不要求外部来源先给全体 runners。只要受控来源给出一个唯一实际出赛马，
该马的 TRA full historical result 会返回整场全体 runners；这正是 targeted path 的主要价值。
若只能取得冠军名，也足以形成 anchor，但仍要核对身份和赛事唯一性。

reviewed-held seed extension 先按 target-key hash 对回 313 条既有 COMPLETE seed。若 organizer-official
occurrence 与旧第三方 winner 一致，则逐字保留旧 seed；若唯一官方 winner 冲突，则旧 seed 必须进入显式
`replace_conflicting_existing_seed` 审核，不能继续复用。本轮因此为 311 条复用、37 条新增和 2 条替换。
扩展输出保持 PREPARED，独立 decision exact 绑定 39 条 candidate 与 350 条 combined ledger 后才能发布
COMPLETE。相同名字在不同 target 获胜时先保留
多个 occurrence seed，取得 provider horse ID 后再去重。

reviewed-held actual-starter census 与 winner seed 分开：winner seed 只需唯一冠军，participant census 必须读取
完整 post-race runner 语义。Sporting Life 的 PU/F/UR/BD/DNF/refused 等保留，withdrawn 排除；ZEturf 的 NP
排除，但 runner table 中未列 arrival 的马仍是 actual starter，具体结果未知时只标
`actual_starter_result_unclassified`。France Galop organizer-official `N partants` 直接证明实际起跑，
`ARR/tbé/–/J/unknown` 不因没有数字名次而丢失。任何来源的 unknown start status 失败关闭。

census 的单位固定为“一匹马在一个 target occurrence 的实际出赛槽位”。同名跨场不合并，source horse key
只作 provenance，不冒充 TRA `hrs_*`；所有 `provider_horse_id` 初始为空。targeted-horse 恢复目标 race 后，
必须按 occurrence/date/course/race/runner status 逐行对回并分配 `hrs_*`，再基于 provider ID 跨场去重。
因此现有 3,192 行 PREPARED census 是 stable-ID 补全的输入分母，不是 profile batch 或生产写入许可。

逐槽位对账由独立 PREPARED proposal 完成：从 held seed proposal 的 existing binding/new candidate 两份映射
恢复 `seed_id -> target_key`，同时必须验证独立批准后的 COMPLETE 350-seed artifact 对 exact proposal、三份
output SHA、decision SHA、非实现者声明与完整 seed set 的绑定，再读取 COMPLETE stable-runner ledger。只给
PREPARED proposal 不能进入对账。每条 TRA occurrence 必须先与 target 的 region/date/grade/discipline 一致且
不是 NR/unknown；随后只在同一 target 内对 source/TRA 名称去国别后双向唯一时生成 binding candidate。同名组、
任一侧未匹配或 runner count 不守恒都进入 review item。即使全部唯一，名称也只是 recall，candidate 仍需
独立 exact-SHA identity review，proposal 自身不写 staging/canonical。

因此一场比赛通常只需要一个外部名字搜索锚点；取得整场 `hrs_*` 后，第二阶段的请求上限按唯一实际
参赛马数计算。单匹稳定 ID 的保守上限为 `results_pages + 2(profile pro/standard) +
2*parent_count`，不再乘 search candidate 数。跨多场重复参赛马只执行一次稳定 ID 补全。

## 2. 数据模型

### 2.1 最小 schema 变化

1. RacingRegion.IRELAND。
2. ExternalDataSource.THE_RACING_API。
3. ExternalHorse 增加可索引的 provider profile 列：
   - breeder_name；
   - damsire_name；
   - sire_external_id/dam_external_id/damsire_external_id。
4. 新增 HorseExternalIdentity：
   - FK HorseProfile；
   - source/namespace/external_id/status；
   - evidence URL、payload SHA、observed/verified/rejected 时间和 reviewer；
   - 唯一约束 (source, namespace, external_id)。
5. 新增 HorseNameVariant：
   - 可绑定 HorseProfile 或 ExternalHorse；
   - raw name、language、script、kind、country suffix；
   - strict/loose normalized keys、source、official flag、valid range；
   - 约束至少绑定一端，避免孤儿 alias。

不在第一阶段把 person/relationship 全部重构为独立产品表。TRA runner 的 trainer/owner 先保留在
immutable raw 和模块 candidate，带 as_of=race date；只有最新且无冲突的 observation 才可
成为 HorseProfile.trainer_name/owner_name 候选。后续若产品需要完整关系史再独立 change。

### 2.2 Scoped reconciliation 与 mixed-source coverage

稳定 ID 第二阶段允许在不放宽单场守恒的前提下增量推进。`--stable-scope-only` 只从完整 held census 中选择
当前 stable ledger 精确引用的 source seed；所选 target 仍执行完整 expected/TRA count、name/position、race
identity 和零 gap 检查。stable ledger 引用 held approval 集合以外的 seed 时立即拒绝，不能把 external sample
伪装成 held member。

不同 source authority 不直接合并成一个伪造 reconciliation approval。中间层
`stable-id-reconciliation-coverage.v1` 保留每个 component 的类型与 manifest，以
`horse_id + race_id + source_targeted_seed_id` 构造 occurrence key。held COMPLETE approval 与 external
single-race COMPLETE approval 可以做集合并集，但必须满足：

- 每个 component 当前 bytes 与上游 stable payload 可重放；
- stable occurrence 全覆盖且只覆盖一次；
- horse-ID set 与 stable ledger 完全相等；
- overlap、gap、SHA 或 payload 漂移全部失败关闭。

coverage 只允许生成零 search 的 request plan；其 manifest 固定 network/database authority 为 false。每个
真实批次仍经过 fresh exclusive proof、exact G3、claim、COMPLETE、identity/module review 与 production apply
门禁。

### 2.3 复用现有表

- ExternalRace/ExternalRaceResult：保存 TRA race 和全体 runner staging。
- ExternalHorse/ExternalHorseHistory：保存 provider profile 与单马 career row。
- RaceEvent/RaceEventResult：只由历史赛事受审 apply 或既有赛事同步链写入。
- HorseProfileDataCandidate：承载 profile/pedigree/race record/major wins 模块 diff。
- HorseRaceRecord：复用 canonical race key 和共享 upsert。
- HorseProfileCompletionRun/HorseP0Source：记录范围来源、运行和 participant 资格。

缺失的正式赛事仍复用 historical detail import：TRA normalized race bundle 先转换为现有受审
historical candidate schema，经过 admission、dry-run、receipt 和 verifier 后写 RaceEvent、
RaceEventRunner、RaceEventResult。该桥不得绕过 historical calendar write guard，也不得由
External staging 自动触发。

### 2.4 数据迁移

choices migration 不重写数据。爱尔兰 reclassification 由独立命令：

1. prepare 生产只读 census；
2. 输出 candidate、strong evidence、ambiguous；
3. reviewed manifest 固定 target IDs 和 before/after；
4. dry-run；
5. apply 时同事务更新 RaceSeries/Target/Event 及受影响关联地区；
6. verifier 证明 GB+IRE 总数守恒、series-target-region 一致、时区正确。

不能写一个按马场名直接批量 UPDATE 的不可审计数据迁移。

## 3. Artifact 合同

每个 run 根目录固定：

    run.json
    request-ledger.json
    target-ledger.jsonl
    occurrence-ledger.jsonl
    non-held-target-ledger.jsonl
    unaccounted-targets.jsonl
    target-ledger-manifest.json
    cache/
      tra/results/<region>/<date>/<skip>.json
      tra/horses/<horse_id>/{pro|standard}.json
      tra/horses/<horse_id>/results/<skip>.json
    normalized/
      races.jsonl
      participants.jsonl
      horses.jsonl
      histories.jsonl
    identity/
      production-census.json
      candidates.jsonl
      decisions.json
    review/
      module-review.json
    release/
      artifact.json
      manifest.json
    summary.json
    errors.jsonl
    COMPLETE

所有 JSON 使用 canonical serialization。manifest 保存文件 relative path、size、SHA-256；拒绝
symlink、目录逃逸、重复 path、缺文件和 extra file。COMPLETE 最后原子发布。

profile/career production apply 的 rolling approval parent 会保留历史 candidate/release，不作为单包边界。
每个 commit artifact 必须独占
`approval/commit_package_<region>_<artifact_sha>/`，且 exact member set 固定为
`reviewed_p0_horse_completion_artifact.json` 与 `manifest.json`。package manifest v2 绑定 artifact relative
path、size、SHA；`p0_horse_production_release_candidate.v2` 再绑定 package manifest SHA。旧 candidate v1
不得进入 commit。package path containment、任一中间目录/member symlink、非普通文件、缺件和 extra file
任一失败都在独立 release approval 与 DB dry-run 前关闭。

单马 results 原始页面只在 cache 保存一次；normalized HorseHistory 仅保存目标马行、race_id 和
source cache SHA，不复制整场 raw JSON。相同 race_id 的完整 race payload 进入内容寻址的共享
cache。完整 raw cache 默认保留到最终验收后 90 天，manifest/hash/receipt/field provenance 长期
保留；保留期到期前不得影响重放与回滚。

共享对象池不放在某个 seed 的私有目录内，而位于 batch root 的
`objects/sha256/<prefix>/<sha256>`。写入者先在同目录写临时文件并 `fsync`，再以 no-replace
语义发布；已存在对象必须逐字节同 hash。每个 seed manifest 只保存对象引用，batch manifest 保存
引用计数和完整对象集合。race 对象按 canonical 完整 race payload hash 去重；profile/parent 对象按
endpoint identity + payload hash 去重；career row 只保存目标 horse row 与 race object hash。并发
writer、resume、GC/retention 都以 batch manifest 和 completed receipt 为存活根，不按目录 mtime 猜测。

run.json 至少绑定：

- schema/tool/policy/openapi version；
- Git SHA、target ledger SHA、source policy SHA；
- regions/year bands/grades/disciplines；
- API entitlement proof SHA；
- request ceiling 与最小间隔；
- output/cache root；
- created_at/resumed_from；
- database_writes=0。

## 4. TRA client 与解析器

### 4.1 HTTP 边界

- Basic Auth 只从 root-owned 0600 secret 文件或环境注入；
- URL 由固定 host/path builder 生成，不接受 artifact 中的任意 URL；
- TLS、无 redirect、timeout、最大 body、content-type、JSON object/list 均校验；
- 日志只保存 endpoint kind、状态、耗时、大小、hash，不保存 Authorization；
- 429 读取 Retry-After；5xx 有界重试；401/403 不重试并 safe-stop。
- 账号级 limiter 与当前 race-live 共用；在共享实现上线前，全量 backfill 只允许在 race-live
  scheduler/runner 关闭且无其他 TRA active claim 时运行。

账号级预算固定提供两种、且每次 run 只能选择一种模式：

1. `shared_db`：常驻 Django/Celery caller 复用现有
   `RaceLiveHostBudget(host=api.theracingapi.com)`。`select_for_update` 预占一个 request slot 后再出
   事务发请求；失败请求同样消耗 slot，响应结果通过 reservation version 回写。backfill 不得降低
   数据库中既有 `min_interval_ms`，只能按更慢的现值执行。
2. `exclusive_file`：仅用于受控 one-shot backfill。G3 必须绑定限时 exclusive-account proof，证明
   race-live、race-data-sync、其他 backfill 和人工脚本均无 active caller；所有本次进程再通过同一
   普通非 symlink `0600` lock/state root 竞争 slot。state 绑定 credential alias、scope manifest SHA、
   request ceiling、累计 attempt、`next_allowed_at` 和 fencing generation；reserve 在发请求前持久化，
   进程崩溃也不得返还额度。429/5xx 的退避推进共享 `next_allowed_at`。

两种模式都以账号为边界，而不是 endpoint、region、worker 或进程为边界。系统时钟回退、state/lock
身份漂移、预算耗尽或并发 scope 不一致均 safe-stop。Montjeu proof 使用 `exclusive_file`；proof
generator 允许作为独立 proof-only G2 在 staging migration 前发布：只读查询
`ExternalDataImportLock.source="the_racing_api"` 使用稳定 provider key，不依赖后续
`ExternalDataSource.THE_RACING_API` choice。该兼容边界不允许创建 TRA import lock、staging row 或绕过
后续 migration；proof-only 发布本身也不读取 credential 或调用 TRA。Montjeu proof 本身不包含
`/v1/results`；未来常驻/并发运行必须使用 `shared_db`。

当 credential/one-shot runner 与 production runtime 不在同一 host 时，exclusive proof 必须同时接收
`runner` 与 `production` 两份 v2 host evidence；每份绑定 role、scope、manifest SHA、hostname 与捕获时间，
且两个 hostname 必须不同。任一端命中已知 runner、证据缺失/过期/角色错配均停止。production 的
settings/DB/Celery/Redis evidence 只补充常驻 caller，不替代 production host 的 process evidence。

### 4.2 分页

- limit=100；
- total/limit/skip/query 必须存在且类型正确；
- 下一页 skip += returned_count，不盲加 100；
- 返回空页但 skip < total、重复 page hash、total 倒退、相同 race_id 内容冲突均停止；
- 完成条件为累计 canonical row count 与 total 一致。

### 4.3 响应规范化

Profile：

- 保留 hrs_*/sir_*/dam_*/dsi_* 前缀校验；
- 从 name 拆 raw 与 country suffix，但永远保留原字符串；
- DOB 为 ISO date；sex/colour 保存 raw + normalized；
- Pro 404 才回退 Standard，其他错误不伪装成 fallback。

Race/result：

- race_id、date、off_dt、region、course/course_id、race_name、type/class/pattern、距离、going/surface；
- runner 的 horse_id/name/position/number/draw/time/weight/prize、person/parent IDs；
- position code 规范为 finished/started_non_finish/disqualified/non_runner/unresolved；
- source raw 不直接进入 RaceEventResult.finish_position，沿用稳定排序位与 official/raw 字段策略。

## 5. 赛事匹配

匹配分两层：

1. 强 identity：已审核 target <-> TRA race_id。
2. 初次候选：region + local date/year + normalized course + pattern + race name alias。

初次自动绑定要求恰好一个候选，且 grade/discipline 无冲突。赞助名可通过受审 alias 去除；不能用
通用模糊相似度跨同日多场比赛选择第一名。确定后将 race_id 写入 mapping decision，后续重放只认
mapping 和 payload hash。

当前生产已有 4,673 imported target 可从 event/result/source_refs 生成强 census；其余 target
以 TRA 和 targeted anchor 逐项解析。

TRA 结果唯一绑定且 runners 完整后，未 imported target 进入 historical candidate bridge；只有
正式 RaceEvent/Result receipt 验证成功，target 才从 race_result_resolved 推进到
production_race_resolved。

## 6. 马匹身份

### 6.1 Provider 层

ExternalHorse(source=the_racing_api, horse_id=hrs_*) 唯一。所有目标赛 occurrence 先按
hrs_* 去重；同名不同 ID 保持不同马。单一 ID 后续改名时新增 name variant，不创建第二
provider horse。

### 6.2 Canonical 层

Identity resolver 建立以下索引：

- 新 HorseExternalIdentity；
- 兼容读取 HorseProfile.source_refs.horse_identity_verified_keys；
- JRA/JBIS/HKJC ExternalHorse 与 aliases；
- profile 的 DOB/sex/sire/dam 和受审英文/本地名称。

自动 disposition：

- bind_verified_external_id；
- bind_official_crosswalk；
- bind_strong_biodata；
- create_new（四字段完整且无候选）；
- ambiguous；
- blocked_conflict；
- provider_profile_missing。

create_new 仍需要 reviewed decision，并创建 draft TermEntry/HorseProfile；没有中文名允许
TermEntry 待译，不能用英文填充中文字段。

生产写前先运行 `build_racing_api_horse_identity_census`。它不修改数据库，而把 all-staged 或显式
`hrs_*` scope 的 provider-ID set、ExternalHorse snapshot、resolver decision/current identity、official claim
trust 状态和 candidate profile snapshot 写为 content-addressed JSONL/manifest/COMPLETE。相同 DB snapshot、
固定 generated-at 与 scope 必须逐字节一致；该 census 是后续 proposal 的审计输入，不是 approval。

### 6.3 Reviewed identity apply 与撤销

只读 resolver 的输出不能直接写 identity。prepare 生成 canonical JSONL，逐马绑定：ExternalHorse
主键和 snapshot SHA、provider ID、disposition、候选 HorseProfile、强字段比较、证据 URL/hash 和
预期现有 identity/name-variant 状态。reviewer 只能把行批准为 `bind_existing`、`create_draft`、
`reject_binding` 或 `leave_unresolved`；approval 文件逐字绑定 manifest SHA、row 集合、审核人和时间。

apply 使用 TRA source-wide lock 和单批事务：

- `bind_existing` 创建或重定向唯一 `HorseExternalIdentity` 为 `verified`，并把 TRA source-display alias
  同时绑定到 canonical profile；同 provider ID 已绑定其他 profile且未有显式 reject/rebind 行时阻断；
- `create_draft` 只能通过既有 P0 profile module/release 链创建 draft，再回填 identity，identity service
  自身不私建另一套 HorseProfile 写链；
- `reject_binding` 保留 provider row，将 identity 标为 rejected 并记录 before/after，不删除 alias；
- `leave_unresolved` 永不进入 apply scope。

每次 commit 产生 append-only receipt 与 exact reverse ledger。reverse 只有在 identity/name variant 和
profile snapshot 仍等于本次 after-state 时才能恢复 before-state；发生后续合法变更时拒绝。split 仅表示
撤销错误 provider binding，不自动拆分已经混入同一 HorseProfile 的其他资料；后者必须另建受审修复包。

### 6.4 跨语言

- 日本马：JRA/JBIS 本地 ID + 官方欧字名为 bridge；TRA 名称只作英文 provider alias。
- 香港马：HKJC full HorseId + 中英双语 + DOB/父母；裸 brand number 仅检索。
- 海外赛事出现日港马英文名时，复用 crosswalk 后的 canonical profile。
- 只有名称相似时停在 review。
- `HorseNameVariant.is_official` 只是名称元数据，不是身份授权。日港双向 variant 只有在 evidence URL 与
  payload SHA 完整，且 authority host 与 profile 的 reviewed local namespace 对齐时，才进入
  `bind_official_crosswalk`。当前显式 authority 对齐为 JRA=`*.jra.go.jp`、JBIS=`*.jbis.or.jp`、
  NAR=`*.keiba.go.jp`、HKJC=`*.hkjc.com`；其他地区的一等 source 要求 source/region/host 同时一致。
- 日港 authority URL 还必须命中 horse-record 路由，且 URL 中的 horse ID 与 verified local key 精确一致；
  只匹配 host 或引用同站另一匹马的页面均不可信。
- proposal profile snapshot 保存 variant 的 external horse linkage、有效期和 evidence URL/SHA。布尔 official
  标记、证据、链接或有效期在审核后变化，均要求重建 proposal；可信与未可信跨 profile claim 并存时阻断。

## 7. 单马资料与完整生涯

每个目标 hrs_*：

1. 拉 Pro；404 拉 Standard；
2. 提取父母 ID，并用全局 parent pool 拉父母 profile；
3. 拉 /{horse_id}/results 全分页；
4. 从每场完整 runners 中只提取目标 horse_id 的 record；
5. race payload 全局按 race_id/hash 去重；
6. 生成 HorseRaceRecord module；
7. 从 records 计算 stats 与 major wins。

完整度分层：

- provider_profile_complete：Pro 必需字段齐；
- page_profile_complete：基础字段 + 二代血统齐；
- provider_career_complete：分页 count 与 total 齐；
- authority_career_complete：有独立总出赛数/官方逐场权威 proof；
- local_identity_complete：需要本地 ID/本地名称的日港马完成 crosswalk。

页面可显示 provider career，但内部 badge 必须诚实区分 provider complete 与 official verified。
在役马在新 racecard/result 发现时增量刷新；退役或长期无新赛马在 90 天后低频复核。任何增量
都生成新 observation/revision，不覆盖不可变历史 cache。

同一 batch process 以 `(URL, allow_not_found)` 为键缓存逐字节规范化 JSON 响应，目标马、父母、search
和 results 的重复 GET 只产生一次账号请求；每个 seed 仍记录其逻辑引用，content pool 继续按内容寻址
去重。cache 不跨进程/断点恢复持久化，因此 request ceiling 仍按所有 remaining seeds 的最坏值计算，
不会因预计命中而降低账号预算。

artifact 层同时生成 `horse-page-field-matrix.v1`，逐字段保留 `value/status/source`，而不是把 TRA 候选
直接当成正式页面值。矩阵覆盖英文名、国别后缀、出生日期、性别、毛色、繁育者、父母和二代血统，
并从完整 career race 中按日期提取练马师/马主 as-of observation、逐场履历、出赛/胜/亚/季统计和
G1/G2/G3 主胜鞍。退赛保留逐场记录但不计 starts；未知 runner 状态、同日多个不同 trainer/owner、
profile damsire 与 dam profile sire 不一致均保持 unresolved/conflict 并阻断完整标记。中文展示名、
原名、日文名和 racing region 仍由本地 identity/人工审核提供；matrix 不越过 manual lock，也不写库。

完整度因此至少拆成：provider profile 字段齐全、页面候选字段齐全、provider 分页/唯一 race 守恒、
本地身份已确认。provider 返回重复且内容相同的 race row 时按 stable race ID 折叠；分页总行数仍保留
审计，但 career 完整投影按 unique race count 对账，不能把合法重复行误报为缺一场。

materialize 阶段必须同时恢复字段矩阵和每个冻结 HTTP response wrapper，不能只保留 normalized JSON。
`racing-api-horse-p0-candidate.v1` 随后从 manifest-bound response 生成零 canonical 写入审核候选：profile
字段必须绑定 Pro/Standard response，每一条 career record 必须能回指至少一个包含相同 race ID 的
`/{horse_id}/results` response。候选只可为 `review_required` 或 `blocked`；provider career 即使分页守恒，
在逐场 authority 未独立审核前仍标记 `count_aligned_records_unverified`，不得进入 strict production apply。
NR 保留为 `did_not_start`，`1DH/2DH/3DH` 先规范为数字名次再计算结果；manual lock 冲突、response URL/
时间/hash 漂移、履历行缺 response、日港新 profile 缺官方本地 crosswalk 都必须阻断。

响应 allowlist 再拆为 evidence 与 discovery 两类。严格 `name`/`q` search 不进入字段证据；同名候选的
非目标 `/results` 只有其稳定 ID 已出现在同包 search response 中时才可作为只读 `discovery_probe` 排除。
目标 Pro/Standard 与声明 parent Pro/Standard 则必须把 response canonical payload SHA 精确绑定到 normalized
profile/parent 及字段矩阵 source refs。这样既容纳真实同名马 occurrence 消歧，也拒绝任意未披露马匹端点、
未声明 parent 和 payload 替换。

既有 `HorseNameVariant` 是 canonical profile 的正式名称证据层之一。生产 mapping 的名称召回和 profile
snapshot 必须包含这些 variant；这样经审核的 JRA/JBIS/HKJC 本地名、官方欧字名及 TRA 海外英文 alias
可以回到同一 profile，同时任何 variant 增删都会改变 snapshot SHA，使旧 mapping decision 失效。

## 8. 批次与容量

### 8.1 请求估算公式

设唯一目标马数为 H、平均 career 页数为 P、唯一父母 profile 数为 A、日期结果页数为 R、
targeted search 数为 S：

requests = R + S + H(profile) + H*P(career) + A(parent profile) + retries

在真实 census 前不写死总请求。G3 包必须从冻结 target/horse artifact 计算上界，并另加不超过
10% retry reserve。默认速率 4 req/s；按 100,000 请求估算纯节流时间约 6.95 小时，实际要加
网络、解析和退避时间，因此采用可跨日 resume。

### 8.2 分片

- target batch：单 region + 单年 + 最多 250 races；
- horse batch：单 home-region bucket + 最多 100 horses；
- parent batch：全局 ID 去重后最多 250；
- apply batch：默认 100 profiles，单事务；每批独立 receipt；
- execution ledger 要求 ordinal 连续，不允许跳批或重复 active batch。

## 9. 写入与回滚

### 9.0 TRA historical bridge 精确接口

TRA 赛事只有在 target ledger 与生产 `HistoricalRaceEventTarget` 的受审 reconciliation 唯一绑定后才能
进入正式桥。bridge adapter 读取 COMPLETE TRA normalized package 和 production target snapshot，输出
现有 historical detail candidate 的 runners/results/basic/source 字段；`source_provider` 固定
`the_racing_api`、authority 固定 `licensed_api`、host 固定 `api.theracingapi.com`，并绑定 response body
object hash、request URL、fetched_at 和 TRA race ID。

旧 import layer 的 `historical_through_2024` 与冻结的 `current_year_due@2026-07-15` 合同保持不变。
本 change 新增独立 `graded_horse_backfill` layer，manifest 必须固定 `as_of_date`：只接受
`2000-01-01 <= local_date <= as_of_date`、目标年份与上述 edition-year/受审跨年规则一致、状态 finished、完整 actual
starters/results，且单 chunk 不超过 250 targets。它继续调用同一 `materialize_historical_event`、
`apply_approved_detail_source`、`apply_authoritative_event_fields`、`apply_historical_target_candidate` 和
`HistoricalRaceDetailImportReceipt`；不新增第二条 RaceEvent 写链。runner 仍为 APPLY-only、network=false，
dry-run 回滚、completed receipt replay 和 verifier 语义保持不变。

### 9.1 Prepare

读取 artifact 和生产 census，零写输出预计：

- create/update/noop profiles；
- new identities/name variants；
- records insert/update/noop；
- events/results bridge；
- conflicts/blockers；
- 字段 before/after 和 manual lock 影响。

### 9.2 Dry-run

在当前生产快照运行与 commit 相同校验和事务代码，最终 rollback；证明：

- migration/schema 兼容；
- 全部 reviewed SHA 精确匹配；
- unique constraints 不冲突；
- canonical race key 与旧记录接管唯一；
- major wins/stats 计算一致；
- re-run 为 noop。

### 9.3 Apply

- 开 maintenance；
- 确认无 active external import/历史写入/竞态 claim；
- maintenance preflight 必须在同一 host-local deployment lock 原 token 的连续持锁窗口内生成并消费；
  proof 最长 5 分钟，精确绑定 artifact/package/release/candidate、batch/ordinal、revision/image、数据库
  identity 与 lock metadata。proof 只读且不构成 apply 授权；commit 前必须即时复核；
- `apply_plan_id` 是跨多个 source rolling batch 的同一生产序列，`source_batch_id` 只标识本次 reviewed
  manifest；ordinal 对 plan/region 连续，不能让每个 source batch 都从 1 重新开始；
- Beat 必须停止、全部预期普通 worker 完整 idle、专用赛事 worker absent；`celery` 与 `race_sync_v2` 为 0。
  `race_live` 仅记录长度并保持不变，严禁为取得 preflight 而清理或消费；
- 十个 `RACE_DATA_SYNC_*` 开关与 race-live 调度开关逐项为 false；expired-but-claimed 仍阻断；
- custom-format pg_dump，size/mtime 稳定、SHA、pg_restore --list；
- 按 approved batch plan 执行；
- production apply 只写受审 profile/pedigree/career canonical 行，不在 receipt 事务后自动发布页面、QQ、邮件
  或赛事数据；公开发布必须是另一个可验证阶段，否则 receipt 的 after-state 会被附带写入立即污染；
- 每批 commit 后立即 verifier；
- 失败停止后可从最后 completed receipt 继续，不能跳过失败 ordinal。

### 9.4 回滚

- 网络阶段：丢弃未完成 run，无生产影响。
- 代码/choices migration：回滚代码；爱尔兰 choices 本身不改行。
- 数据 apply：优先用每批 exact reverse ledger 还原 before state；跨多表或 verifier 不可信时恢复
  写前 dump。
- 不删除 scope 外 profile、TermEntry、records 或人工数据。

## 10. 调度

历史 backfill 由专用一次性 runner 控制，不挂常驻 beat：

- 每批预算耗尽、429 窗口、部署窗口都可 safe-stop；
- 可运行频率以 4 req/s 上限和账号月额为边界，而不是固定每天一批；
- 当日建议先完成一个 region/year target batch，再执行相应 horse batches；
- active/current-year 增量另建日更 schedule，只有正式结果出现时入账。

直到历史 ledger 全部 resolved 前，状态报告每次必须包含：run terminal state、请求 ledger、target/race/
participant/horse/profile/career 增量、blocker/gap 和数据库 receipt；不能只报告队列长度。
provider/source/identity gap 只表示当前批次安全停止，仍须排入替代来源或人工 resolution，不能
作为整个 change 的完成条件。

## 7.4 Stable-ID enrichment 的最小批准面

zero-gap reconciliation 由独立 publisher 重放所有来源与 TRA 输入；只有 expected slots、TRA occurrences、
unique bindings 三者完全一致，且 review/count/unmatched 全为 0，才可形成 COMPLETE bindings。该 COMPLETE
事实层仍不授权网络或数据库写入。

稳定 `hrs_*` 的 enrichment plan 固定 `search_requests_per_seed=0`。execution ledger 据此把 G3 endpoint
scope 缩为 results、Pro 和 Standard-on-404；旧 name-seed plan 无该字段时才保留 search。默认分页上限
201 页、profile ceiling 2、最多两个 parent profile 各 2 请求，合计 207 GET/马；5 马/批、单并发、
≥250ms、批间 ≥30 分钟。分页达到 ceiling、total drift、career 缺目标 occurrence 或任何身份 SHA 漂移均
safe-stop。计划、网络、identity review、staging apply 与 production apply 继续是五个独立批准面。

## 11. 最终全局完成证据

旧 current completion audit 保留为单批次诊断。最终完成另使用四层集合守恒：

进入这四层前，materialization 与 External staging 会在任何 DB transaction 前重验 exact member/manifest/marker，
并对 batch/run/materialization/seed/compact/normalized/response JSON 使用 duplicate-key-free、non-finite-free decoder；
歧义不兼容。

同一约束从最早 ingress 开始执行：网络 client 在缓存 HTTP 200 body 前严格解析；OpenAPI fingerprint、单马
targeted seed、bulk target manifest/ledger 与 targeted seed ledger/batch-definition/checkpoint 也只能由 strict decoder 读取。
SHA/marker 是字节身份，不是 JSON 单义性证明，两类校验必须同时通过。

bulk range 的恢复边界固定为 provider page。run root 永久保留 `batch-definition.json`、`checkpoint.json` 和
按 range/page 命名的 cache；definition 绑定 plan/OpenAPI/ranges/总 ceiling，checkpoint 绑定每页 receipt、每次
attempt request ledger 与累计请求。异常将当前 attempt 终止为 `safe_stopped`；execution ledger 只有在重验同一
G3 scope、fresh proof、checkpoint/cache 与剩余额度后才发新 claim。恢复 client 是全新实例，ceiling 为剩余额度，
runner 从下一 skip 继续。完成时 checkpoint 先变为 complete，再生成 normalized/manifest/marker；stable-ID builder
再次验证 definition/checkpoint/member set 和压缩后的 request URL 序列与成功 response pages 一致。这样 HTTP retry
可以多计请求，但不会把 retry 次数误当成功 page 数，也不会在 resume 时重复消费已验证页。

1. exact merged stable ledger + global coverage 冻结全局 `hrs_*`/occurrence 分母；merged manifest 必须恰含
   冻结 bulk plan 的 `N_bulk` 个 bulk + 65 targeted 唯一 source stable identities；本次为 88+65=153，
   pilot 或较小分母不能进入后段；
2. 已验证 proposal prefix 可在后续网络批次等待时进入人工 identity/module review；frontier 固定 template/rows/SHA
   与 reviewer evidence，并按 verified-ID、crosswalk、strong biodata、observed-ID、create-new 跨语言防重、blocked
   cohorts 分流，但绝不自动批准。module publish 还会从 exact candidate bytes 重建所有 review rows 与 deterministic
   manifest，防止 rehashed 摘要绕过人审输入。全部双 approval 齐套后，再从 complete/inactive enrichment ledger 与六类
   exact batch children 自动生成不可变 binding artifact，禁止人工逐行拼 JSONL；global review aggregation 随后严格
   重载 wrapper，并独立重放证明每批 exact identity/module approval，而非 proposal；
3. `generate_racing_api_global_completion_inventory` 从 exact merged ledger 逐马读取 canonical DB，核验 verified
   identity 及其未 reverse identity-review receipt、full profile、complete career、最新未 reverse production
   receipt 的 live after-state；
4. 独立 production public verifier 消费第三层 manifest SHA 与 `hrs_* + profile_id + public_path`，保存 fetch time、
   HTTP/body SHA 和页面模块检查。

第三层只写本地 immutable artifact，不发 HTTP、不写数据库、不发布 profile。它会输出 `inventory.jsonl`、
`public-page-targets.jsonl`、`manifest.json` 与最后发布的 `INVENTORIED_READ_ONLY` marker。数据库层全部通过时状态可为
`COMPLETE_READ_ONLY`，但 `completion_achieved` 仍固定 false；只有第四层及全局 approval 聚合一起通过，并且
identity receipt artifact SHA 与 production receipt 持久化的 module approval manifest SHA 逐马一致后，final audit
才可生成 `AUDITED_COMPLETE`。

production receipt 以 profile 当前最后一个未 reverse receipt 为终态。较早 receipt 可因合法后续 apply 漂移，不作为
最终 blocker；最后 receipt 漂移则阻断。两个 provider `hrs_*` 指向同一 profile 时同时标记 blocker，避免跨语言或
provider duplicate 被静默折叠。

第四层实现采用两阶段 artifact。`prepare` 仅消费 exact inventory，按 `PUBLIC_HORSE_RACE_RECORD_PAGE_SIZE=20`
生成一行一页的 immutable plan；第一页固定 `/horses/<id>/`，后续页仅允许 `?records_page=N`。`execute` 重验
plan 全部成员、marker/SHA、horse/profile/page/record 切片与 exact URL 后才调用 injected fetcher。真实命令额外使用
CLI+env 双门禁，`requests.Session.trust_env=false`、无 credentials/cookies、禁止 redirect、单并发、间隔至少 0.5 秒，
每页最多读取 5 MiB。单次 execute 强制为最多 50 个连续 ordinal，逐块发布
`VERIFIED_CHUNK_COMPLETE/INCOMPLETE`，避免全量 HTML 驻留内存与长时中断清零；零联网 merge 重新读取所有 chunk、
响应 bytes 与页面合同，只有 1..request_count 无 gap/overlap 的 exact coverage 才发布最终 marker。公开模板只新增
无副作用的 `data-horse-profile-id`、record count/page/pages 及逐场 record ID/key，
供 verifier 排除“200 但串马/缺页/错序”。每次响应原文、SHA、逐页 blockers 与 aggregate SHA 独立落入 evidence；
这一层仍不自行生成 `AUDITED_COMPLETE`，最终集合守恒由后续 final audit 完成。
