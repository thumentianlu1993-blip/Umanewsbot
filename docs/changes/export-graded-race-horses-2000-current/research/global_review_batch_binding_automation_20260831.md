# 全局 review batch binding 自动化

日期：2026-08-31

## 问题

全量 zero-search enrichment 预计产生大量 batch。原 global review aggregate 虽会重放每个 candidate、identity
proposal/approval 与 module proposal/approval，但入口仍要求操作者预先提供手工拼装的
`batch-bindings.jsonl`。这会把“是否漏批、错填 SHA、混入 pilot”留给人工操作，且无法从 complete execution ledger
确定性重建。

## 已实现合同

`prepare_racing_api_global_review_batch_bindings.py` 只接受：

- exact plan root、plan manifest SHA、batch-plan SHA；
- 已完全结束且 `active=null` 的 execution ledger；
- materialization、candidate、identity proposal、identity approval、module proposal、module approval 六个绝对 parent。

六个 parent 的直接 child set 必须各自恰等于 planned batch IDs。producer 按 plan ordinal 逐批重放
materialization→candidate→proposal 守恒，并重验两类 approval 的 exact member、marker、manifest、proposal SHA、
decision count 与 horse set；跨批 `hrs_*` 必须互斥且全局并集等于 plan stable horse set。execution ledger 在运行期间
发生字节漂移也会失败。

成功时原子发布私有目录：

- `batch-bindings.jsonl`
- `manifest.json`
- `COMPLETE`

三者固定 `network_requests=0 / database_writes=0`，不授予 review、apply、publish、public fetch 或 production
maintenance 权限。

## 下游双重重放

`prepare_racing_api_global_review_aggregate` 首选
`--batch-bindings-root + --batch-bindings-manifest-sha256`。命令先严格重载 wrapper 的 exact member/marker/manifest/
rows，再把 frozen JSONL 交给原 aggregate producer；后者仍独立重放全部 child artifact 和 merged stable
denominator。因此 automatic wrapper 只消除人工接线，不成为可绕过审核的新信任根。

raw `--batch-bindings + --batch-bindings-sha256` 只保留兼容诊断；raw 与 automatic artifact 模式必须二选一且成对
提供。

## 验证与真实状态

- producer 专项：`6/6`；
- Django wrapper/command/aggregate：`3/3`；
- complete/inactive、extra pilot、incomplete ledger、approval proposal SHA drift、已发布 artifact extra member、命令输入
  互斥均有回归。

这些测试全部使用 synthetic/filesystem-only evidence。真实 global enrichment execution、identity/module approval 与
binding artifact 仍为 0；event 956 未释放窗口前继续不拿共享锁、不停 Beat、不触碰 registry、不做生产联网或数据库写，
旧 `race_live=7543` 不变。

另以现有 13 马 zero-search plan 做真实本地零状态演练：plan manifest/rows SHA 为
`51eccdcca26edc3d7aebd7cf8b945953f6895cc11052e0694e4e7a236a4fc230 /`
`20f099584adeb46266c81335de61bebba5675994a505d5cf7e4ba46349e0b137`，execution ledger SHA 为
`573f2ac1c3153f8ca086e9bc1ff1fb60102c8bb5706794483cf4405c4dbd9840`。producer 按设计 exit 75：
`global review bindings require one exact complete child per planned batch`；临时 parent 顶层成员数为 0、binding output
absent。演练未生成 proof/claim/network/DB 状态。
