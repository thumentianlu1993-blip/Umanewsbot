# France / Ireland mixed-source stable-ID reconciliation coverage

## 结论

当前 France 2023 与 Ireland 2024 两场真实样本已经形成 13 个唯一 `hrs_*`、13 个
horse-occurrence 的精确 reconciliation coverage。该 coverage 只证明二阶段零 search 补全计划的输入集合完整，
不授权 TRA 网络、production staging、canonical 写入或公开发布。

## 输入与产物

| 产物 | SHA-256 | 计数 |
| --- | --- | ---: |
| merged stable-ID v2 manifest | `bce82b2fc84d5f26f25fa800f346af20c4cbeebcf3a8b4d1da7b3734af488a8b` | 13 horses / 13 occurrences / 2 targets |
| France scoped held proposal | `798df10b1270147720cf45ffb41cc54ea9d1ee3edc2b7ae2ca0db745b0cd9376` | 1 target / 5 bindings |
| France scoped held approval | `433659a49652c5896cb233f452fbefbe21a7fc71cf74fd682169417ba88efaae` | 5 approved bindings / 0 gaps |
| Ireland external approval | `9033993d82bc79b2dfcfbddbfb26358dc534cedc3e729ac366f36d905af2f73d` | 8 approved bindings / 0 unmatched |
| mixed-source coverage manifest | `a3e8963ba923d5f227b70903341a4f58bef148279781726abbe3416621f5c964` | 13/13 covered / 0 overlap / 0 gap |
| zero-search plan manifest | `51eccdcca26edc3d7aebd7cf8b945953f6895cc11052e0694e4e7a236a4fc230` | 3 batches / 13 horses / 2,691 GET ceiling |

France scoped proposal root：

`/Users/mentianlu/.codex/umanews-france-scoped-held-reconciliation-v1-20260831`

France scoped approval root：

`/Users/mentianlu/.codex/umanews-france-scoped-held-reconciliation-approved-v1-20260831`

coverage root：

`/Users/mentianlu/.codex/umanews-france-ireland-reconciliation-coverage-v1-20260831`

plan root：

`/Users/mentianlu/.codex/umanews-france-ireland-stable-enrichment-plan-v1-20260831`

## Scoped held reconciliation 合同

`prepare_held_census_tra_reconciliation.py --stable-scope-only` 不是降低完整 held census 的守恒标准。它只把
输入 target 集合缩到 stable ledger 精确引用的 held source seed；被选中的每个 target 仍须满足：

- source census 与 TRA runner 数量一致；
- 每个 expected starter 只绑定一个 `hrs_*`；
- 没有 review、source gap、TRA gap 或 count gap；
- stable source seed 必须存在于独立批准的 held 350-seed artifact；
- proposal 与 publisher 重放相同 scope、输入 manifest、member set 和输出 SHA。

不属于 approved held map 的 source seed 不得混入 scoped held proposal，必须走独立 external-result approval。
当前 Ireland 样本因此保持为外部单场批准组件，没有伪装成 held 350-seed 的成员。

## Mixed-source coverage 合同

`build_stable_id_reconciliation_coverage.py` 以
`(horse_id, race_id, source_targeted_seed_id)` 作为 canonical occurrence key，将多种已批准组件做集合并集：

- held component 必须是 COMPLETE reconciliation approval；
- external component 必须是 COMPLETE single-race actual-starter approval；
- 每个组件的当前 manifest、输出和上游 stable payload 都要重验；
- union 必须与 stable ledger 的 occurrence key 集合逐项相等；
- 任一 overlap、gap、horse-ID 集合漂移或 component SHA 漂移立即失败关闭。

coverage manifest 固定 `planning_eligible=true`，同时固定
`network_execution_authorized=false / database_write_authorized=false`。它不能替代 fresh exclusive-account
proof、exact G3、identity/module review、备份、apply approval 或 verifier。

## 零 search 补全计划

13 匹马被拆为 3 个串行批次：France 5 匹、Ireland 5 匹、Ireland 3 匹。每马最坏上限为 201 页 results、
目标 profile 的 Pro/Standard fallback 与最多 2 个 parent profile，合计 207 GET/马；计划 ceiling 为 2,691 GET，
批间最小 60 分钟，最大并发 1，账号级最小请求间隔 250 ms。

ordinal 1 France 2023 G3 proposal SHA 为
`bae59c28dd65721cc41ea05adde97bb901cc838a189862b2592d9e0dc482f201`，默认批准后的 manifest SHA 为
`1228acefb4a10df031cb5575db7dad2f826e82fb60bc4f8b78a43102a25aa2d6`。endpoint scope 仅含：

- `horse_results`；
- `horse_pro`；
- `horse_standard_fallback_on_404`。

不含 `horse_search`。execution ledger 仍为 `active=null / completed=0`；没有 fresh proof、claim、output 或
request-budget 目录，也没有发出请求。

## 验证与当前阻断

- scoped reconciliation/publisher、coverage、planner 聚焦回归 `25/25`；
- 完整 `runtime/research` 回归 `532/532`；
- change test_cases 共 263 个 ID 且无重复；
- 生成过程网络请求 0、数据库写入 0；
- event 956 的 result/public/correction 验收仍占用赛事窗口。在 owner 明确让出窗口前，不 acquire shared
  lock、不停 Beat、不触碰 `740a…cff2` reference registry 或 `3bac…a6da` TRA canonical、不运行 proof/claim。

## Next-batch read-only preflight

等待窗口期间，execution ledger 新增 `preflight` action。它复用 claim 的 exact scope/argument/spacing 校验，
但只读既有 ledger，不加载 proof 或凭据、不创建 lock/output/budget，也不写 ledger。

真实 France ordinal 1 preflight 返回 `ready_for_fresh_exclusive_proof`，识别 5 seeds、1,035 GET，endpoint 仅为
results/profile/standard-fallback。execution ledger SHA 在运行前后均为
`573f2ac1c3153f8ca086e9bc1ff1fb60102c8bb5706794483cf4405c4dbd9840`，lock 空文件 SHA 均为
`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`；output/budget 目录保持 absent。

新增后 execution-ledger 专项 `6/6`、完整 research `534/534`，change test_cases 265 个 ID 无重复。该结果只
证明本地命令身份已就绪；event 956 放行后仍须重新 preflight、采集 fresh proof，再由 runner 自 claim。
