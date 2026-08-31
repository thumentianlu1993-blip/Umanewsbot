# pre-2005 targeted 两段 stable-ID postprocess frontier

## 问题

65 个 pre-2005 targeted batches 的网络 COMPLETE output 是 content-addressed compact artifact，必须先离线物化为
完整 `targeted-horse-batch-materialization.v1`，才能用现有 builder 投影 actual starters 的稳定 `hrs_*` ledger。
此前 selected-batch 工具只覆盖第一个现场批次，不能证明 65 个 completed receipt、materialization 与 stable ledger
全量一一齐套。

## 方案

新增 `audit_targeted_stable_id_postprocess_readiness.py`。两个专用 parent 都采用固定 `<parent>/<batch-id>` child。
审计重验 exact plan/execution ledger、COMPLETE batch receipt、materialization manifest/run/normalized/response 全成员、
stable manifest/ledger 全成员，以及每条 actual-starter occurrence 的 horse/race/seed/run/race/runner payload。

状态为：

- `waiting_for_targeted_completion`；
- `materialization_required`，只给最早缺失 batch 的离线 materializer argv；
- `stable_postprocess_required`，只给最早缺失 stable 的 builder argv；
- `ready_for_global_stable_merge`，严格要求 65/65 COMPLETE、materialization、stable 且 active=null。

额外 child、stable orphan、extra member、symlink、source batch 或 occurrence bytes 漂移全部失败关闭。命令自身
`network_requests=0 / database_writes=0`，不创建未来 parent。

## global coverage authority

stable ledger 生成后，每个 materialization 以 `provider_native_targeted_materialization` component 进入 global
coverage。builder 会重放完整 materialization、actual starters 与 expected stable occurrence，要求在最终 merged
lineage 中恰好存在一个 source stable ledger。planner 再加载 materialization/source stable，核对 lineage、component
binding rows 与 binding SHA。这样 1,128 个 pre-2005 occurrences 有明确 provider-native authority，不需要冒充 held
或 external census approval。

## 真实只读重放

- plan manifest/rows SHA：
  `a0eab1c30ebeec6f69c3a59d2bfb0a2fa7d9a0673759ddf103e20a1a5d19f5f9` /
  `efe4243e35a447bd10642e502fb161f2c2b7f8fac3b5a061f9017bdd055fe933`；
- execution ledger SHA：`8f9d51cc9dc81eaec1f0b72b307ed6dbe9d96157230e0a4d2efd0524afc6a50d`；
- 当前：65 planned、0 completed、0 materialization、0 stable、active=null；
- 状态：`waiting_for_targeted_completion`；
- 生产网络/数据库写：`0/0`。

随后组合 source frontier 将最终 merge 固定为 32 bulk + 65 targeted，并排除 13 马 pilot；最新完整 research 为
`558/558`，相关链 `28/28`，test IDs `300/300`。event 956 未明确释放窗口前，仍不生成
proof/claim，不停 Beat，不触碰 registry、生产网络或 DB。
