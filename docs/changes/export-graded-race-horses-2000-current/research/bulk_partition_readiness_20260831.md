# The Racing API 全量 bulk 分区 readiness（2026-08-31）

## 结论

reviewed COMPLETE target 的全量请求路线已能离线确定，但尚不可执行：12,048 个目录目标中 11,935 个已
到期，10,791 个属于 2005+ bulk-results 路线，1,144 个属于 2000–2004 外部锚点后单马 results 路线，
113 个 not-due 不进入结果请求。

当前状态为 `BLOCKED_ENTITLEMENT_PROOF_AND_EXECUTION_PLAN`，不是“凭据一注入即可全量导出”。还缺 fresh
historical bulk/North America entitlement proof、range runner、exact G3、execution ledger 和 event 956
可暂停窗口。

## 冻结输入与输出

- target root：`/Users/mentianlu/.codex/umanews-target-reviewed-complete-20260829.9WzJJH`
- target manifest/ledger SHA：`a130d11a59d4324e92e8d3d02185aa48633b330e0561ce020d8b2d893956903f` /
  `de5aabfb70257ba65d407cbf05f431595180ef475d0efd768438dca7b17b4264`
- coverage root：`/Users/mentianlu/.codex/umanews-source-coverage-not-due-aware-v4-20260830.5ghcHz`
- coverage manifest/plan SHA：`44fb91ab1e10ad1f992d4fcabca98b7189e7bac60dc6e97a7fd499059b633faf` /
  `7dfe417d708e5ac2abfd68b6e805286dd3fdd50d7746db33e3507d48acfb4bec`
- 输出：`/Users/mentianlu/.codex/umanews-bulk-partition-readiness-v2-20260831.g3IXpI/artifact`
- report SHA：`5e8c603f2a381512e5583644aa8870536396ddc36b0ea2b75be5cba2062d8701`
- partition/bulk/pre-2005/not-due SHA：`7882975b…dedd / f277984b…a157 / d543e988…cd5f /
  eddf9550…308a`

全部输出为 `network_requests=0 / database_writes=0 / execution_ready=false`，`PREPARED` 只绑定 report SHA。

## 地区分账

| 地区 | 2005+ bulk | 2000–2004 anchor | not-due | region-year | date ranges | ceiling GET |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| France | 1,642 | 176 | 73 | 22 | 27 | 5,427 |
| Ireland | 1,804 | 153 | 0 | 22 | 27 | 5,427 |
| United Kingdom | 2,888 | 266 | 40 | 22 | 27 | 5,427 |
| United States | 4,457 | 549 | 0 | 22 | 27 | 5,427 |
| 合计 | 10,791 | 1,144 | 113 | 88 | 108 | 21,708 |

每个区间按 `limit=100 / skip<=20000` 得到最多 201 页。21,708 GET 是所有区间都触顶的协议最坏值；按
4 req/s 仅请求时间为 5,427 秒，即 90.45 分钟，不含重试、proof、批间隔、审查或 provider 实际响应时延。

## 为什么需要 range runner

10,791 个 bulk target 中只有 1 个有精确 `local_date`，其余 10,790 个只有年份和赛事身份字段。现有
`racing_api_bulk_results_export.py` 只支持单日请求与单日 target 过滤，无法承接全年/半年区间。正确实现应：

1. exact-SHA 读取本 readiness 的 region-year partition 与 bulk target set；
2. 对普通年请求全年，对闰年请求两个半年，对 2026 请求到 `as_of_date=2026-08-29`；
3. 完整分页、保存原响应 SHA，并按 `race_id` 检查跨页/跨区间冲突；
4. 按 year/name/course/grade/discipline 唯一映射 target；
5. 将 missing/ambiguous 与 non-runner 单独保留，不按名称自动补齐；
6. 只从 actual starters 提取 `hrs_*`，再跨批稳定 ID 去重并进入 zero-search enrichment。

## 不可执行 range batch plan

`prepare_racing_api_bulk_range_batch_plan.py` 已把 88 个 region-year 单元按同地区顺序装箱，每批最多 4 个
日期区间，不拆分一个年度单元。权威输出为：

- root：`/Users/mentianlu/.codex/umanews-bulk-range-batch-plan-v3-20260831.cG4nP5/artifact`
- manifest SHA：`2578ac6fe256c537903ecc981797d1ccd4ef7e56336771f4bc2a47ddb1aa4a5b`
- plan SHA：`9c4c23cfcdc17034f1bff08dc4872563a178db0cdc58a50e92853537e4cfde0c`
- 32 批，每地区 8 批；单批最大 804 GET，4 req/s 理论 201 秒；并发 1、批间 30 分钟。

plan 为 `PROPOSED_NOT_APPROVED / approval=false / execution_ready=false`。它为每批保存完整 target ledger 与
exact SHA。range paginator 与 artifact core 已能离线完成多区间合并、唯一 target 对账、actual-starter 投影及
COMPLETE/PREPARED receipt，但刻意没有 standalone 网络入口。execution ledger 已实现下一 ordinal proposal、
独立 approval、fresh proof claim、complete/safe-stop；safe-stop 暂无 page checkpoint，因此不允许隐式重试。
不得直接用于网络调用。此前未绑定收紧后工具的
readiness/plan 目录保留作历史重放证据，由上述 v2/v3 roots 取代。

首批本地 proposal 为 France 2005–2007：105 targets、3 ranges、603 GET，proposal SHA
`d7711b39ebdd503b9c71ee54f161ab01aca0a86854851687650a5a26617f8d59`，execution root
`/Users/mentianlu/.codex/umanews-bulk-range-execution-v1-20260831.G5Z4ox`。当前无 approval、proof、claim，
ledger 为 `active=null / completed=[]`，生成过程 0 网络、0 DB 写。

## pre-2005 anchor readiness

`audit_pre_2005_anchor_readiness.py` 现将 1,144 个早期目标同时与 TOBA、France、Ireland、UK、US external 与
US archive supplemental proposal 做 exact-SHA 对账。v12 取代只计数 correction 的 v11，唯一当前输出为：

- root：`/Users/mentianlu/.codex/umanews-pre-2005-anchor-readiness-complete-v12-20260831.YjcYhO/artifact`
- report SHA：`152d660add78547d5fd478f549098509d6617bf5526f448d29f5ae766cc5dd37`
- prepared-anchor SHA：`597ba78a03a19a06b1a440b5a7cb3757e051ab478621f87879f807dd87eed31a`
- calendar-correction SHA：`4a7818c82b230d48f23a5020cad3887e415ad4d5337e2a108a1e4eef89ded886`
- unresolved SHA：`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
- denominator：1,144 = 1,128 winner anchors + 16 not-held/corrections + 0 unresolved；
- 地区分账：France `176/0/0`、Ireland `153/0/0`、UK `256/10/0`、USA `543/6/0`
  （anchor/not-held-or-correction/unresolved）；
- approved anchors：0；provider horse IDs：0；Ireland 另有 24 行 actual-starter candidates。

France proposal 仍绑定 `431d576c…b34ab / 99cbae8f…0464a / 379d2717…62f7`。Ireland Wikipedia proposal
由 v3 root `h0CFhG` 给出 151 anchors/2 gaps，随后 IrishRacing direct proposal root `qSq2mC` 将两行补齐并提供
24 行实际参赛马 candidates。UK proposal root `2bRrOI` 给出 256 anchors 与 10 not-held。US flat 继续绑定
TOBA manifest `7617092b…65df` 与 automatic bindings `46300bfc…ecc`；US jump external proposal root
`xDo9FL` 用 17/17 份 SHA-bound capture 提出 31 anchors、2 corrections 和 3 个待补证行。随后 archive capture
root `xMyM6r` 用 3/3 个固定时间戳 Wayback PDF 补齐这些行；manifest/request-budget/cache-manifest SHA 为
`f0c295af…fc28 / 7563dc90…2b7 / a3974ef9…cf90`。supplemental proposal root `eSLa7V` 的 manifest、anchor、
correction、empty-unresolved、cache-binding SHA 为 `a029db15…4973 / ff8d3646…3de5 / 5a0a6936…572c /
e3b0c442…b855 / 4b3e6c32…1398`。

最终补证固定 2002 Atlanta Cup winner=`Pinkie Swear`，2004 Hard Scuffle=`not_held`，2004 U.S.
Championship Supreme Novice winner=`Cherokeeinthehills`；不得把该赛事误绑到 `Praise The Prince`。早期失败或
不完整 capture roots 仍全部排除。所有 proposal 仍为 `PROPOSED_NOT_APPROVED`，所以 source-route 未决为 0
不等于 source approval，winner name、not-held row 或 actual-starter candidate 都不能当 `hrs_*`。

## pre-2005 date-optional targeted seed proposal

reviewed target 的 2000–2004 行没有 exact `local_date`；v11 winner candidates 中 477 行由 TOBA/IrishRacing
提供精确日期，651 行只有 edition year。为避免伪造日期，新增 `targeted-horse-seed.v2`，但日期缺失时必须绑定：

1. `year` 与 `edition_year`；
2. `country_region`；
3. reviewed canonical name 与 source/target aliases；
4. reviewed racecourse 与可审别名；
5. grade 与 discipline；
6. winner 来源 URL、payload SHA、source proposal manifest SHA；
7. expected finish position=1。

TRA 搜索只能产生候选 `hrs_*`。每个候选都必须在其完整 career results 中得到恰好一个符合上述结构化身份的
赛事，而且该马是实际参赛的预期名次；零匹配或多匹配都失败关闭。这个规则不会把 winner name 当稳定身份，
最终跨语言/同名去重仍只使用 provider `hrs_*` 与后续 identity review。

当前不可执行提案为：

- root：`/Users/mentianlu/.codex/umanews-pre-2005-targeted-seed-proposal-v2-20260831.S3ikU7`
- manifest SHA：`6bd861849f6d9341e2198b063dfdca027e94a9150c3026dd30873d3fd3c9b464`
- proposed seed SHA：`90692b01c9f2b8de2efebe5af5ac3e62b2647159b9677ece722483e2148b04d0`
- evidence SHA：`45fc7b028364cfed397b463173f19969c02de43c110598b9c0b0db123f5ba7ab`
- `1128 = 477 exact-date + 651 edition-year-only`；France 176、Ireland 153、UK 256、USA 543。

proposal 使用 runner 不接受的 `proposed-targeted-horse-seed.v2`。publisher 会从 exact-SHA source inputs 重新
生成并对比全部行，只接受独立 reviewer、精确 outputs 和
`SOURCE_ANCHOR_SEED_PUBLICATION_ONLY_NO_NETWORK_OR_DATABASE_WRITE` scope；发布后也明确
`network_execution_approved=false`。默认批准后的 COMPLETE root 为
`/Users/mentianlu/.codex/umanews-pre-2005-targeted-seed-approved-v2-20260831`，manifest/ledger SHA 为
`acb97c16…b951 / 7e085d54…49ee`；这不是网络批准。

16 个非参赛项另外形成 calendar-correction proposal：root
`/Users/mentianlu/.codex/umanews-pre-2005-calendar-correction-proposal-v1-20260831.CdMXxX`，manifest/output SHA
`16287df2f7a72c6ccd4182dd73addcc3e7932869604319156b4d95b418d8bfbc /`
`ebd1eaf022dd366fc97d7d613b3cd971e481e7e1b195ce2e1ba97116e8da94fa`。分账 UK 10、USA 6；approval publisher
只接受 `CALENDAR_CORRECTION_PUBLICATION_ONLY_NO_DATABASE_WRITE`，且输出固定
`database_apply_approved=false`。默认批准后的 root 为
`/Users/mentianlu/.codex/umanews-pre-2005-calendar-correction-approved-v1-20260831`，manifest/ledger SHA 为
`f7103943…07fdf / fa9a8213…161c`；没有数据库 apply。

## 验证

- range 相邻专项：`20/20`；
- US archive capture/supplemental proposal/readiness 聚焦：`18/18`；
- 完整 `runtime/research`（项目 venv）：`524/524`；
- `py_compile`：通过；
- `git diff --check`：通过；
- 真实 readiness build：0 网络、0 数据库写入。

该验证不包含真实 TRA range 请求，也不改变 UK/USA sample、registry、shared lock 或 event 956 状态。

## 2026-08-31 bulk next-batch read-only preflight

bulk execution ledger 现提供只读 `preflight_next_batch_execution`。它与 claim 共用 exact next scope 和批间隔
校验，但只读已有 ledger，不加载 exclusive proof、不创建 output/budget、不 claim，也不发出网络请求。

真实 ordinal 1 France 2005–2007 preflight 结果：

- 105 targets / 3 region-year units / 3 date ranges；
- request ceiling 603；endpoint 仅 `bulk_results`；
- approval/proposal SHA：`52b8b0861e5280d136d81d3ab7b90b7cd865702ffd5838acba5461dfec2c46f0 /`
  `d7711b39ebdd503b9c71ee54f161ab01aca0a86854851687650a5a26617f8d59`；
- ledger SHA 前后均为 `6c83d21a29004b3ec40fb3d060b4701f17fe3cc109a7b8a9adda812f87261c47`；
- lock SHA 前后均为 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`；
- batch output 与 account budget 目录保持 absent，network/DB=0。

新增后 bulk execution-ledger 专项 `4/4`，完整 `runtime/research` `536/536`。该 preflight 只证明本地执行
身份与 G3 一致；event 956 放行后必须重跑现场 preflight，再生成 fresh proof 和 claim。

同日对 pre-2005 targeted ordinal 1 France 2000 运行共享 targeted preflight：20 winner anchors、320 GET，
endpoint 为 search/results/profile/fallback；approval/proposal SHA 为 `78ea5faf…bae0 / 15c0a53d…694e`。
ledger/lock SHA 前后为 `8f9d51cc…a50d / e3b0c442…b855`，output/budget absent。它与 stable-ID France 2023
的 zero-search scope 是两个不同 G3，放行后不得并发或交叉复用参数。
