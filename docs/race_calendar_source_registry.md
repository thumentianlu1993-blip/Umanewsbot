# 赛事日历来源注册表（九地区）

> 适用范围：2025 年起的赛事日历与赛果采集。比赛范围为国际分级赛 G1/G2/G3（含英爱法障碍 Grade 1-3、日本 J-G1~J-G3）+ 地方一级赛（日本 NAR Jpn1；中东仅 ICS 国际认可场次）。
> 配套历史目录来源（1984 起逐年细节）见 [historical_race_catalog_sources.md](historical_race_catalog_sources.md)。

## 总原则

1. **全集基准（ground truth）= IFHA《International Cataloguing Standards》蓝皮书**：每年 4 月发布当年版，整本 PDF 位于 `https://www.tjcis.com/pdf/icsc{两位年份}/{year}_EntireBook.pdf`，季后升降级/变更见 `PostPub{year}.pdf`。凡 ICS Part I 收录的 G1/G2/G3 即为国际认可分级赛全集；解析时以每个国家章节末尾的官方计数行（`Total Graded/Group races`、`Number of G1/G2/G3 races`）做自校验，不一致即失败，不得输出"空成功"。
2. **ICS 定集合与级别，官方赛历定日期/马场/冠名**：ICS 不含比赛日期；日期、马场、赞助冠名以各官方赛历为准。两边对不上的条目（ICS 有而官方赛历无 = 停办/改名；官方有而 ICS 无 = 本地分级或未获国际认可）必须进人工审核队列，不静默丢弃。
3. **变更追踪三层**：(a) 年内 ICS PostPub 附录；(b) 区域 Pattern Committee 公告（欧洲 Pattern Committee / Asian Pattern Committee / APC via ARF）——级别变更通常比下一年 ICS 早半年；(c) 官方赛历版本号/修订日期。
4. **赛果采集官方优先 + 第三方交叉**：每地区至少双源；官方源写 `approval_authority=official`，可信第三方写 `human_reviewed_reference`（见 decisions 2026-08-16 同等置信度口径）。
5. **年份口径**：跨年赛季地区（香港 9-7 月、澳洲 8-7 月、中东 11-4 月）一律按 `local_date` 实际公历年归属（主线 `derive_public_year`），赛季标签保存在 `season_label`/`source_refs`。
6. 所有抓取低频限速、请求预算、source cache + SHA-256；空结果 fail closed。

## 全局基准来源

| 来源 | URL | 用途 | 备注 |
|---|---|---|---|
| IFHA ICS 蓝皮书（当前版） | `https://www.tjcis.com/default.asp?content=ICS` / 整本 `https://www.tjcis.com/pdf/icsc26/2026_EntireBook.pdf` | 全球 G1/G2/G3 全集与级别认定 | 每年 4 月新版；解析器 `runtime/tools/prepare_tjcis_ics_catalog.py` |
| IFHA ICS 历年版 | `https://www.tjcis.com/default.asp?content=PASSYR` | 1998 起历年骨架 | 1998 之前不可用 |
| ICS PostPub 附录 | `https://www.tjcis.com/pdf/icsc{yy}/PostPub{year}.pdf` | 季后升降级/变更勘误 | 必须与同年正本一起使用 |
| The Racing API（TRA） | `https://www.theracingapi.com` | 临近赛事出马表/赛果同步（race_data_sync 登记体系） | 覆盖：英/爱/港完整，法/日/德/澳/阿联酋为 group 级，沙特极弱；合同 registry 有 `valid_until`，需定期续验 |

## 日本（区分 JRA 中央 / NAR 地方）

### JRA（中央）

| 用途 | 来源 | URL / 说明 |
|---|---|---|
| 年度全集/赛程 | JRA 官方重赏一览 | `https://www.jra.go.jp/datafile/seiseki/replay/{year}/jyusyo.html`（G1/G2/G3/J-G1~3） |
| 赛果（官方） | JRA 重赏 replay 结果页 | 上页逐赛事链接；既有 adapter `jra_detail` |
| 赛前出马表 | JRA 赛前页 → `RaceEventDataCandidate(source_name=jra_pre_race_v1)` | 只写候选；身份发现不能依赖 TRA（free 对日为空），见 `docs/reports/2026-09-20-all-comers-lifecycle-root-cause.md` |
| 交叉验证 | netkeiba | 既有 `netkeiba` provider |
| 赛历公布节奏 | 前一年 12 月公布全年重赏日程 | 12 月触发次年全国对账 |

### NAR（地方）

| 用途 | 来源 | URL / 说明 |
|---|---|---|
| 年度全集/赛程 | NAR 官方ダートグレード竞走列表 + 年度 PDF | `https://www.keiba.go.jp/dirtgraderace/{year}/racelist/index.html`（Jpn1 在范围内；Jpn2/Jpn3 存量保留、不主动扩） |
| 赛果（官方） | keiba.go.jp RaceMarkTable | 经 `racecard.html` 自动发现；既有 adapter `nar_detail` |
| 交叉验证 | JBIS | `jbis.or.jp` |
| 赛历公布节奏 | 前一年 11-12 月 | 同上 |

## 中国香港

| 用途 | 来源 | URL / 说明 |
|---|---|---|
| 年度全集/赛程 | HKJC 官方 G2/G3 页 + 赛事中心 + ICS 香港章节 | `https://racing.hkjc.com/zh-hk/international-racing/g2-g3-races/index`、`https://campaigns.hkjc.com/racing-event-hub/ch/` |
| 赛果（官方） | HKJC resultsall → localresults | 既有 adapter `hkjc_detail`；正式赛果可回溯至 1984 |
| 交叉验证 | ICS 香港章节 | 香港在 ICS 不同年代分布于 Part I/II，解析按分册页头切换 |
| 赛历公布节奏 | 赛季前 7-8 月（马季 9 月-次年 7 月） | **注意马季跨年错位**：2025 日历年 = 2024/25 赛季尾段 + 2025/26 赛季初段 |
| TRA 路线 | 完整覆盖，可用于临近登记 | 已在 standing policy |

## 英国

| 用途 | 来源 | URL / 说明 |
|---|---|---|
| 年度全集/赛程 | BHA 官方 Pattern/Listed 年册（Flat + Jump 两册分开解析） | `https://www.britishhorseracing.com/about/publications/pattern-and-listed-race-books/`；2026 Flat PDF 无文字层时需 OCR（2026-07 已验证可行） |
| 赛果 | Sporting Life racecards/results API + 结果页 | 既有 adapter `uk_sporting_life_detail`；`human_reviewed_reference` |
| 交叉验证 | Racing Post（仅限 G1 且遵守既有许可：≥300s/次、≤5 次/日）、irishracing.com | RP 许可不覆盖 G2/G3 |
| 赛历公布节奏 | Flat 前一年 9-10 月；Jump 赛季书春季 | Jump 跨年赛季按 local_date 归年 |
| TRA 路线 | 完整覆盖 | 已在 standing policy |

## 爱尔兰

| 用途 | 来源 | URL / 说明 |
|---|---|---|
| 年度全集/赛程 | **HRI RÁS Flat Pattern 年册 PDF** + ICS 爱尔兰章节 | `https://www.hri-ras.ie/flat-pattern-races`（2026 版直链 `.../2026-FlatPattBook.pdf`）；ICS 2026 爱尔兰：G1×14 / G2×13 / G3×45（平地），另有障碍章节 |
| 全年赛期历 | HRI 年度 Fixture List | `https://www.hri.ie/.../2026-Irish-Racing-Fixture-List-(Weekly).pdf`；**2027 版已于 2026-09-24 公布** |
| 赛果（官方） | HRI RÁS results / results archive | `https://www.hri-ras.ie/results`（按马场+年份检索） |
| 交叉验证 | irishracing.com | 服务端渲染、URL 含日期/马场，历史可回溯至 1990 年代；已被既有 uk/france 详情源复用 |
| 赛历公布节奏 | **前一年 9 月下旬**（HRI 新闻稿） | 9 月底触发次年全国对账 |
| TRA 路线 | 完整覆盖（2025 年 2,892 场） | 可登记；加入 standing policy 待实施 |
| catalog adapter | `hri_pattern_catalog`（2026-09 新增） | ICS 解析 `Pt I—IRELAND`/`IRE` + Irish Jumps 页头 |

## 法国

| 用途 | 来源 | URL / 说明 |
|---|---|---|
| 年度全集/赛程 | France Galop 官方 groupes/listed PDF（平地 + 障碍两册） | 例：`groupes_listed_plat_2026_v7.pdf`、`groupes_listed_obstacles_2026_v4.pdf`；版本号滚动更新 |
| 赛果 | France Galop 官方结果（当前重定向认证页，不稳定）→ ZEturf 兜底 | 既有 adapter `france_zeturf_detail`；France Galop 恢复可访问后优先切回 |
| 交叉验证 | Geny / irishracing / Racing Post（G1 许可内） | |
| 赛历公布节奏 | 当年初滚动版本（v1→v7…） | 年内需按版本号重抓对账 |
| TRA 路线 | 量级可用 | 已在 standing policy（另有 zeturf result-only 兜底） |

## 美国

| 用途 | 来源 | URL / 说明 |
|---|---|---|
| 年度全集/赛程 | TOBA/AGSC American Graded Stakes 官方年表 | `https://toba.org/graded-stakes/{year}-races/` |
| 赛果 | Equibase chart（防护页时不可批量）→ Horse Racing Nation 兜底 | 既有 adapter `us_hrn_detail` + `us_equibase_results`（PDF）；HRN 不公开结果块的大赛只入出马表 |
| 交叉验证 | ICS 美国章节 / DRF | |
| 赛历公布节奏 | 前一年末 TOBA 年表 | |
| TRA 路线 | 北美全量属 regional add-on（未购） | 主用既有源；standing policy 已有 united_states TRA 路线 |

## 澳洲（赛季 8 月 1 日-次年 7 月 31 日）

| 用途 | 来源 | URL / 说明 |
|---|---|---|
| 年度全集/赛程 | **Racing Australia 官方 Group/Listed 全国表** + ICS 澳洲章节 | `https://racingaustralia.horse/FreeFields/GroupAndListedRaces.aspx`（2026: G1×76 / G2×94 / G3×167）；分州赛期 `Calendar.aspx?State=…` |
| 分级变更官宣 | Asian Pattern Committee / ARF 公告 | 每年 7 月（如 2026-27：Apollo Stakes 升 G1、Stan Fox 降级） |
| 赛果（官方） | RA `Calendar_Results.aspx?State=…` 分州赛果；Racing NSW / Racing Victoria | 各州官方结构不同，优先 RA 汇总 |
| 交叉验证 | Racenet `racenet.com.au/group-one-races`、Punters、breedingracing.com 赛季表 | breedingracing 含冠军/父系，结构化好 |
| 赛历公布节奏 | 各州 4-6 月（RV 2026-04-30）；7 月 RA 全国表刷新 | 赛季 8/1 开始前落地；**赛季跨年按 local_date 归年** |
| TRA 路线 | 仅 group 级（2025 年 403 场），全量为 regional add-on（暂不可购） | 不作主源；可做 G1 级临近补充 |
| catalog adapter | `racing_australia_pattern_catalog`（已存在） | providers: racing_australia + tjcis |

## 德国

| 用途 | 来源 | URL / 说明 |
|---|---|---|
| 年度全集/赛程 | **Deutscher Galopp 官方 Renntermine PDF** + ICS 德国章节 | `https://www.deutscher-galopp.de/gr-wAssets/docs/renntermine2026.pdf`（2026: G1×7 / G2×9 / G3×26） |
| 赛果（官方） | Deutscher Galopp Ergebnisse | `https://www.deutscher-galopp.de/gr/renntage/ergebnisse/` |
| 交叉验证 | galopp-sieger.de（历年冠军库）/ turf-times.de 年度 black-type 汇总 | turf-times 年度计数可与 ICS 对账 |
| 赛历公布节奏 | 前一年 12 月中旬，1 月修订 | 12 月触发次年对账 |
| TRA 路线 | 仅 group 级（2025 年 74 场） | 不作主源 |
| catalog adapter | `deutscher_galopp_pattern_catalog`（已存在） | |

## 中东（阿联酋 + 沙特；卡塔尔/巴林仅 ICS 收录时）

**级别认定必须以 ICS 为准**：阿联酋为 ICS Part I（2026: G1×7 / G2×13 / G3×13，全部国际认可）；沙特为 Part II（本地等级仅国内有效），仅沙特杯赛日 7 场经单独评审获国际认可（Saudi Cup G1、Neom Turf Cup G1、Riyadh Dirt Sprint G2、1351 Sprint Turf G2、Red Sea Turf G2、Saudi Derby G3〔2027 起升 G2〕、Custodian of the Two Holy Mosques Cup G3）。本地宣传的"G1"不得直接采用。

| 用途 | 来源 | URL / 说明 |
|---|---|---|
| UAE 全集/赛程 | **Dubai Racing Club Carnival 赛程+条件 PDF** | `https://drcwebblob.blob.core.windows.net/drcwebmediacontent/…/Dubai Racing Carnival {season} Race Schedule and Conditions.pdf`；Meydan 赛历 `meydanracing.com/full-race-calendar/` |
| UAE 赛果（官方） | Emirates Racing Authority | `https://emiratesracing.com/racecard/{yyyy-mm-dd}/{raceNo}/results`（服务端渲染可用；赛季历页为 SPA，必要时解析其后端接口或用官方 PDF） |
| 沙特全集/赛程 | JCSA 官网赛历/赛事页 + 沙特杯官网 | `https://jcsa.sa/en/`；沙特杯 2027 = 2027-02-05/06 |
| 沙特赛果（官方） | JCSA meetings/races/results | 同上 |
| 交叉验证 | horse-races.net / TDN / America's Best Racing | |
| 赛历公布节奏 | DRC 前一年 7 月；JCSA 前一年 8 月中旬 | 赛季 11 月-次年 4 月，跨年按 local_date 归年 |
| TRA 路线 | 阿联酋 223 场/年（group 级），沙特≈无 | 官方为主 |
| catalog adapter | `middle_east_official_pattern_catalog`（已存在，providers: era/jcsa/qrec/bahrain_turf_club/tjcis） | 生产地区键为单一 `middle_east`，国家经 series key 前缀与 source_refs 区分 |

## 临近同步（出马表/赛果/状态流转）路线现状

- 已登记路线全部为 TRA：france / hong_kong / japan(jra+nar) / ireland / united_kingdom / united_states（`runtime/policies/race_data_sync/standing_policy.json`）；sporting_life / zeturf / horse_racing_nation 为 result-only 挂接兜底。
- **已知缺陷**：日本 TRA free 出马表返回空导致身份发现无产出、赛事不登记（2026-09-20 根因报告）；census 只收未开赛赛事、T+5 后身份发现停止、SLO 只监控已登记集合。修复属阶段 3。
- TRA 合同 registry（`runtime/policies/race_live/source_registry_the_racing_api_free.json`）有 `valid_until` 与 31 天 `verified_at` staleness 门禁，到期前必须续验。
