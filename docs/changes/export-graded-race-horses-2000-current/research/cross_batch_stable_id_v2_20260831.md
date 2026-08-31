# TRA actual-starter 跨批次 stable-ID v2 总账

日期：2026-08-31（Asia/Shanghai）
状态：实现与 France/Ireland 真实 partial artifact 完成；UK/USA 与全量批次尚未执行
副作用：0 TRA 请求、0 数据库写入、0 production 变更

## 结论

旧 `target-runner-stable-id-ledger.v1` 只能在一个 targeted batch materialization 内按 `hrs_*` 去重。多年全量
导出会由多个初始 target batch 逐步发现 actual starters；同一匹马参加多个目标赛事时，v1 无法把跨批次
occurrence 合并成一个 enrichment seed，可能重复下载完整 profile/career，也无法用一个 canonical 候选证明该马
覆盖的全部目标赛事。

新增 `target-runner-stable-id-ledger.v2`：逐个重验源 v1/v2 ledger 的 manifest/COMPLETE/ledger SHA，把相同
`hrs_*` 合并为一行，合并英文 source names、全部 target occurrences 与所有 source targeted-batch manifest
SHA。相同 race ID 的 target/payload/seed 身份必须全等；同一 horse/race 被重复提供或发生冲突时失败关闭，
不静默选一份。

既有 held-census reconciliation、stable-ID enrichment planner、targeted batch loader/request budget 与
zero-search horse runner 已同时兼容 v1/v2。v2 不使用名字搜索，仍直接请求已验证 `hrs_*` 的 profile、parents 与
完整 results，并逐一复核所有 target occurrences。

## 真实 partial artifact

根目录：

`/Users/mentianlu/.codex/umanews-four-region-stable-id-v2-partial-20260831.PvIXEM`

| 产物 | manifest SHA-256 | actual starters / target races |
| --- | --- | ---: |
| France v1 ledger | `dd6d003e025799fbf0a267f0fc842d8c995f1ff077102813bee1d66ed62a0024` | 5 / 1 |
| Ireland v1 ledger | `c13ec0fa83aee06e1a68423a66e33de7b41c3b02e0467388aa3418dde6e2c3bb` | 8 / 1 |
| merged v2 ledger | `bce82b2fc84d5f26f25fa800f346af20c4cbeebcf3a8b4d1da7b3734af488a8b` | 13 / 2 |

合并 ledger SHA-256 为
`096cfbaaf99bd659fb04d115f63b52cb38e885a0f0543e80852e98504c53802f`，共 13 个唯一 `hrs_*`、13 个
horse-occurrence、2 个唯一 target race；当前两场没有跨批次重复马，因此
`cross_batch_duplicate_horse_count=0`。这已把真实样本范围从“两匹冠军 profile”扩展为“两场全部实际参赛马的
稳定 provider ID”，但另外 11 匹尚未执行 profile/career enrichment。

## v2 合同

- manifest：`target-runner-stable-id-ledger.v2`；seed：`targeted-runner-stable-id-seed.v2`；
- seed 使用 `source_targeted_batch_manifest_sha256s`，不把多个来源伪装成单一 manifest；
- source ledger 至少两份，root + manifest SHA 不可重复；输出目录必须 absent/empty；
- `hrs_*` 是跨语言主键；source names 仅保留为别名/召回证据，不参与跨马合并；
- occurrence 保存 race ID、race payload SHA、runner payload SHA、原 targeted seed 与 materialized run SHA；
- 输出仍为 `network_requests=0 / database_writes=0`，COMPLETE 精确绑定 manifest。

## 验证与边界

- 新 merge 专项覆盖跨批同马合并、来源 SHA 集合、v2 downstream loader 与 duplicate occurrence fail-closed；
- v1/v2 request ceiling、zero-search runner、reconciliation、enrichment plan 相邻回归 `65/65`；
- `runtime/research` 全量 `422/422`，`py_compile` 与 `git diff --check` 通过；
- merge tool/test SHA-256：`b7733040…c3bf` / `f2b56f22…91ac`。

该 partial artifact 不等于 held-census reconciliation approval、profile enrichment、identity/module approval、
production apply 或公开页验收。UK/USA sample 和后续所有 initial target batches 完成后，应把每批 ledger 追加到新
v2 merge artifact；不得原地修改本次 partial bytes。

## Enrichment readiness 精确审计

readiness artifact：

`/Users/mentianlu/.codex/umanews-stable-enrichment-readiness-partial-20260831.xuksSv/artifact`

该首份报告 SHA-256 为 `0f98bcd9bf79d6d5d97cc37f0011155f0a9fd52bfa9f582b7746791355c77569`；当时状态为
`BLOCKED_SOURCE_CENSUS_AND_APPROVAL_GAPS / execution_ready=false`。

- v2 ledger 的两个 source seed 中，France `legacy-winner-40574…` 已存在于 350-target held proposal；
- Ireland `sample-winner-b2f8aa…` 不在该集合；后续已将 2024 Irish Champion Stakes 的冻结页面转换为
  8 马 source census/candidate crosswalk proposal，但仍未批准，不能把样本 reference 冒充 held approval；
- 350-target held proposal 自身仍是 `PREPARED_NOT_EXECUTABLE`，且没有独立 COMPLETE approval；
- 即使以上均关闭，仍须生成 exact census-to-TRA reconciliation proposal/approval。

更新后的 readiness artifact 位于
`/Users/mentianlu/.codex/umanews-stable-enrichment-readiness-with-ireland-20260831.g6UaYP/artifact`，报告 SHA 为
`5c7a0c747090e853dc18437e585cf6b6041f10aaac2ba3bff1cd7e51f30f4d54`。它确认当前 partial scope 的
`uncensused_occurrence_seed_ids=0`，状态细分为 `BLOCKED_EXTERNAL_CENSUS_AND_APPROVAL_GAPS`；external
census/crosswalk、held seed 和 reconciliation 的独立批准仍全部缺失。

只作容量估计时，13 个唯一马按每马最坏 201 results 页 + profile/fallback + 2 parent 的 ceiling 为 207 GET；
France 5 马 1 批上限 1,035 GET，Ireland 8 马 2 批上限 1,656 GET，总计 3 批、2,691 GET、批间最小跨度
60 分钟。该上限不是实际请求预测，也不授权联网。最初 readiness 工具专项为 `3/3`；加入 external census
proposal、独立 publisher 与 unsigned review packet 后聚焦为 `14/14`，研究全量更新为 `436/436`。

## 2026-08-31 approved readiness 更新

项目默认批准随后发布了两份只读事实产物：

- held 350-seed COMPLETE：manifest `5e77b325ffe8be494e141ecca6366155145f2d071b03160e937d5b958c779d1e`，
  ledger `6e91cc1f679ba95219f8d60f4e5d4cdbe3aceed0b8ad0f83c066f4040031deda`；
- Ireland one-race external census COMPLETE：manifest
  `9033993d82bc79b2dfcfbddbfb26358dc534cedc3e729ac366f36d905af2f73d`，approved crosswalk
  `80f6786ca420f1ff4b879eef181c95e6cc55b46eab2c09a72e187ef948e2b698`。

readiness auditor 已支持并严格重验这两类 approval。当前权威产物为
`/Users/mentianlu/.codex/umanews-stable-enrichment-readiness-approved-v3-20260831`，报告 SHA
`5367540bdfbbd87a677b84e2a42ddeb12ba7d75d72ede7d1d3cff90723e1d502`：2 个 occurrence seed 已 2/2
approved，unapproved/uncensused 均为 0；状态为
`BLOCKED_APPROVED_RECONCILIATION_MISSING / execution_ready=false`。全局 350-seed artifact 中只有 1 个 seed
被当前 partial ledger 引用，因此 approved held occurrence count 为 1，不是 350。

较早 `approved-v2` 报告把全局 seed 总数直接并入当前 occurrence 分子，出现 `351/2`，该报告层计数错误已由
新增交集回归修复，v2 不得用于验收。readiness 专项 `8/8`、完整 research `527/527`；本轮依旧 0 network、
0 DB write，exact reconciliation approval 与 fresh proof 仍未完成。

## 2026-08-31 scoped reconciliation 与 mixed-source coverage

France stable ledger 只引用 held 350-seed 集合中的一个 target。对账工具现支持 `--stable-scope-only`，仅选择
该 exact source seed 对应 target，但仍要求所选 target 内 expected/TRA runner `5/5` 全部唯一绑定且零 gap。
真实 France proposal/approval manifest SHA 分别为
`798df10b1270147720cf45ffb41cc54ea9d1ee3edc2b7ae2ca0db745b0cd9376` /
`433659a49652c5896cb233f452fbefbe21a7fc71cf74fd682169417ba88efaae`。

Ireland source seed 不属于 held map，因此继续使用独立 single-race external COMPLETE approval。新
`build_stable_id_reconciliation_coverage.py` 将 France held approval 与 Ireland external approval 按
canonical occurrence key 做精确并集；coverage manifest SHA 为
`a3e8963ba923d5f227b70903341a4f58bef148279781726abbe3416621f5c964`，结果为 13/13 covered、0 overlap、0 gap。
coverage 只提供 `planning_eligible=true`，network/DB authority 均为 false。

由此形成真实 13 马零 search plan：manifest/plan SHA 为
`51eccdcca26edc3d7aebd7cf8b945953f6895cc11052e0694e4e7a236a4fc230` /
`20f099584adeb46266c81335de61bebba5675994a505d5cf7e4ba46349e0b137`，3 批、2,691 GET ceiling、60 分钟最小批间。
ordinal 1 France G3 approval SHA 为
`1228acefb4a10df031cb5575db7dad2f826e82fb60bc4f8b78a43102a25aa2d6`，endpoint 只含 results/profile/fallback，
不含 search。execution ledger 仍 `active=null / completed=0`，没有 proof、claim、网络或数据库写入。

完整设计与证据详见
`research/mixed_source_reconciliation_coverage_20260831.md`。新增合同后完整 research 回归为 `532/532`。
