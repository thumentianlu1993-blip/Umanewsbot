# 法国/爱尔兰真实样本单马页字段验收（2026-08-30）

## 1. 结论

Westover 与 Economics 两份真实 Pro + parent Pro + full horse results 样本证明：TRA 可为现有 UmaFans 单马页
稳定提供英文名、出生国、出生日期、性别、毛色、生产者、父母、二代血统，以及带 as-of 的最新马主/练马师
候选；逐场履历可生成页面统计、主胜鞍和 20 条 started records。

两匹的 19 项 profile field matrix 结果相同：

- `available=14`；
- `local_review_required=3`：中文展示名、正式原名、所属地区；
- `official_crosswalk_required=1`：日文名；
- `optional_unknown=1`：编辑简介。

当前验收结论为：

`REAL_FR_IRE_PROVIDER_FIELDS_COMPLETE_LOCAL_IDENTITY_AND_PUBLICATION_NOT_COMPLETE`

这不是 identity/module approval，也不是 canonical apply。候选仍为 `review_required`，career authority 仍为
`count_aligned_records_unverified / partial`；所有新 profile 默认 draft，不能因 provider 字段齐全而自动公开。

## 2. 冻结输入

| 样本 | run manifest SHA-256 | normalized export SHA-256 | GET / DB writes |
| --- | --- | --- | ---: |
| Westover | `0208b4961089f31cb6e91aebe97ad98c6701a986c90b707ae43a70d9133a8214` | `44faa57c3a516e730098c0e9151c9e2c8a41a43575001d490254bdd0903d3bd0` | 5 / 0 |
| Economics | `8eff6078bda8e50dc6a437e16f308202b9c85a5990548f80934ac483bf8b3a43` | `5b725c25c36a169767b12fd20940967146251057d9362523a8a591920c91709c` | 6 / 0 |

normalized export 分别位于：

- `/Users/mentianlu/.codex/umanews-four-region-sample-run-v4-20260830.ImqC5G/materialized-0001-france-recomputed/00001-d6b834c6c378/normalized/targeted-horse-export.json`；
- `/Users/mentianlu/.codex/umanews-four-region-sample-run-v4-20260830.ImqC5G/materialized-0002-ireland-recomputed/00001-f1a780e33a27/normalized/targeted-horse-export.json`。

本次验收只读这些冻结字节，没有新增 TRA 请求、staging 写或 canonical 写。

## 3. 19 项 profile 字段到 HorseProfile 的映射

| 字段 | Westover | Economics | 状态/落表语义 |
| --- | --- | --- | --- |
| `english_name` | Westover | Economics | available；identity review 后可成为候选 |
| `country` | GB | GB | available；来自 source name suffix，保留来源，不冒充本地注册 authority |
| `birth_date` | 2019-04-24 | 2021-03-01 | available；强身份字段 |
| `sex` | horse | colt | available；保存 provider 冻结分类，不按当前年龄自行改写 |
| `color` | b | ch | available；保留 provider 原枚举/规范化证据 |
| `breeder_name` | Juddmonte Farms Ltd (Gb) | Copgrove Hall Stud | available |
| `owner_name` | Juddmonte | Isa Salman Al Khalifa | available candidate；非无时间含义的永久事实 |
| `trainer_name` | Ralph Beckett | William Haggas | available candidate；非无时间含义的永久事实 |
| `sire_text` | Frankel (GB) | Night Of Thunder (IRE) | available；同时保留 parent provider ID/SHA |
| `dam_text` | Mirabilis (USA) | La Pomme D'Amour (GB) | available；同时保留 parent provider ID/SHA |
| `sire_sire_text` | Galileo (IRE) | Dubawi (IRE) | available；parent Pro |
| `sire_dam_text` | Kind (IRE) | Forest Storm (GB) | available；parent Pro |
| `dam_sire_text` | Lear Fan (USA) | Peintre Celebre (USA) | available；profile + parent Pro 一致 |
| `dam_dam_text` | Media Nox (GB) | Winnebago (GB) | available；parent Pro |
| `display_name_zh` | unknown | unknown | local review required；TRA 不权威提供中文展示名 |
| `original_name` | unknown | unknown | local/official identity review required；不把英文 display 自动等同正式原名 |
| `racing_region` | unknown in provider matrix | unknown in provider matrix | local identity review required；应按 home identity，不按 France/Ireland target region反推 |
| `japanese_name` | unknown | unknown | official crosswalk state；对英国本土马不是公开完整度 blocker |
| `intro` | unknown | unknown | optional editorial；不由 TRA 分析评论自动生成 |

`owner_name/trainer_name` 的冻结 as-of 分别为：Westover `2023-10-01`，Economics `2025-10-18`。当前
`HorseProfile` 只有文本列，没有一等关系历史/as-of 列；本批只能把时间写进 source evidence/source_refs 并作为
人工候选。若产品要展示任期历史，需要独立 schema change，不能覆盖成“永远当前”。

同理，亲本 `hrs_*`/payload SHA 已在 artifact/source_refs 中保留，但 `HorseProfile` 六个血统文本列没有一等
provider pedigree ID 字段；本批可以安全填文本，不应丢弃外部身份边。

## 4. 现有公开单马页实际可消费的字段

当前 `stable/public/horse_detail.html` 和 `public_horse_detail` 会消费：

- hero：display name、原名/英文名、出生年份、毛色、性别、地区、完整度、练马师、主胜鞍；
- 基础资料：country、owner、trainer、breeder、intro；
- 二代血统：父、母、父父、父母、母父、母母；
- 派生统计：starts、wins、seconds、thirds、win rate；
- 参赛履历：日期、赛事、马场、距离、等级、名次、完成时间。

因此 provider 已取得的 14 项 profile 字段、二代血统、统计和履历足以填充页面结构的大部分事实区域；但页面
能否公开仍取决于 canonical identity、review status 和人工发布，不取决于 HTTP 200 或字段非空率。

逐场 artifact/`HorseRaceRecord` 还保留了页面当前未显示的 surface、going、eligibility、马号、档位、负磅、
骑师和奖金。这些字段是已入模型的后续 UI 能力，不应因为模板暂未显示而从导出丢弃。完成时间展示继续使用：
有 confirmed linked `RaceEventResult` 时优先正式关联结果，否则回退到受审 `HorseRaceRecord.finish_time`。

## 5. 20 条逐场记录字段覆盖

两匹合计 20 条 started records；以下字段为 `20/20` 非空：

- race date/name/course/region；
- discipline/surface/distance text/going/eligibility；
- horse number/barrier/carried weight/jockey；
- position/finish time。

真实可解释缺口：

| 字段 | Westover | Economics | 合计 | 处理 |
| --- | ---: | ---: | ---: | --- |
| `distance_meters` | 9/13 | 6/7 | 15/20 | 保留 distance text；不能用固定换算猜被 provider 留空的法国/海外米数 |
| `grade_text` | 11/13 | 5/7 | 16/20 | 4 场本来是 maiden/conditions 非分级，不是数据缺失 |
| `prize_text` | 12/13 | 6/7 | 18/20 | 空值保持 unknown；不从总奖金或其他名次推算 |

所有 20 条都有唯一 provider race ID，并分别绑定同一匹马的单页 results response SHA；0 nonstarter、0
unconfirmed、0 missing/excess/gap。这个守恒仍只证明 provider 返回集合内部完整，独立 module review 前不宣称
四地主办方官方逐场完整。

## 6. 页面派生统计与主胜鞍

| 马 | starts | wins | seconds | thirds | win rate | G1/G2/G3 wins |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Westover | 13 | 4 | 6 | 1 | 30.77% | 3 |
| Economics | 7 | 4 | 0 | 0 | 57.14% | 3 |

Westover 的 3 场主胜鞍为 `rac_10498514`、`rac_10371868`、`rac_10988900`；Economics 为
`rac_11224863`、`rac_11369969`、`rac_11309415`。主胜鞍由逐场记录中“实际获胜 + 当届 G1/G2/G3”确定性
计算，不复制 provider summary，也不把普通胜场算入。

## 7. 仍缺字段/模型能力与验收门禁

当前明确仍缺：

1. 中文展示名、正式原名、所属地区、日文/香港繁中官方名、本地 JRA/JBIS/HKJC identity key；
2. 编辑简介及中文赛事/马场术语审核；
3. owner/trainer 的一等时间关系历史；
4. 亲本 provider ID/crosswalk 的一等 canonical schema；
5. 独立 identity/module approval、production census、canonical apply receipt 和公开页面验收。

此外，本次只有 France/Ireland 两个英国本土马样本。它还不能验证 UK/USA entitlement、North America
add-on、常见同名规模、深分页、日港海外远征跨语言命中率，也不足以冻结全量批次频率。正式频率继续保守为单并发、
至少 250ms 间隔（不超过 4 req/s）、逐批 fresh proof；必须在 UK/USA 样本和独立字段/身份审核完成后再定。

生产 fail-closed 期间，本报告不得用来发布 approval、恢复 proof、并入 shared registry 或执行数据库写入。

## 8. 可重复四地区字段审计入口（2026-08-31）

- 新增 `runtime/research/audit_racing_api_four_region_sample_fields.py`，只接受
  `region=normalized-export-path` 与对应 exact SHA-256；验证 normalized/page-matrix/target occurrence/career
  守恒、四地区唯一 horse ID，并聚合 19 项页面字段与 18 项逐场字段非空率。
- 当前 France/Ireland partial artifact：
  `/Users/mentianlu/.codex/umanews-four-region-sample-field-audit-partial-20260831.ZDfpTC/artifact`；报告
  SHA-256 为 `8752e2134dbdfa3471b9aee07a94c384e257e846a5ed38cdd979b676e14382a1`。
- 结果精确为 `PARTIAL_REGION_SAMPLE_AUDIT`：地区 `2/4`、唯一马 `2`、页面字段 `38`、逐场记录 `20`；
  `available=28 / local_review_required=6 / official_crosswalk_required=2 / optional_unknown=2`，明确缺少
  `united_kingdom / united_states`，不会误标为四地区完成。
- 工具专项 + execution-ledger + materializer 聚焦 `11/11`，`runtime/research` 全量 `420/420`；生成过程
  `network_requests=0 / database_writes=0`。UK/USA materialization 完成后必须对四份 exact SHA 重新生成新
  artifact，旧 partial report 不可改写或冒充终态。
