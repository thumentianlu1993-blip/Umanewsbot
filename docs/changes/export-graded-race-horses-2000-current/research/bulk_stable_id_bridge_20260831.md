# bulk COMPLETE 到全局 stable-ID enrichment 桥

## 结论

原方案的 bulk 网络 runner 能把 2005+ target 对账到 TRA race 并输出全部 actual starters，但既有
`build_target_runner_stable_id_ledger.py` 只接受 targeted-horse materialization。也就是说，32 个 bulk 批次即使
全部 COMPLETE，仍不能进入跨批 `hrs_*` 去重和 profile/career/pedigree 补全。这是全量主线断点。

现已补齐：

```text
COMPLETE bulk run
  -> read-only COMPLETE receipt / stable child 1:1 frontier
  -> deterministic provider-native stable-ID ledger
  -> merge all bulk + targeted ledgers by hrs_*
  -> exact occurrence authority coverage
       - provider_native_bulk_run
       - held_census_reconciliation_approval
       - external_census_occurrence_approval
  -> one global zero-search enrichment plan
```

## 守恒合同

bulk builder 会重验：

- batch run manifest SHA 与 COMPLETE marker；
- frozen batch plan、batch row、target ledger 与 range units；
- request ledger 与逐响应 cache URL/SHA/size；
- normalized reconciliation SHA/size，并用同一 target/race 重新计算全部 mappings、participants、gaps；
- actual starters 与 NR/unresolved 排除；
- run 成员集合只能是 manifest、marker、列明 cache 与 normalized 文件。

输出每条 occurrence 保存 target key、bulk batch/run manifest SHA、race payload SHA、runner payload SHA、provider
`hrs_*`、名字和名次。输出仍是 `network_requests=0 / database_writes=0`。

## 全局去重边界

单个 bulk stable ledger 不进入 enrichment。全部 32 个 bulk ledgers 与 targeted ledgers 先由 v2 merger 按
`hrs_*` 合并；同一马跨年份/批次保留全部 target occurrences，只生成一个 enrichment seed。coverage builder 会
递归读取多轮 merge lineage，让每个底层 bulk run 精确覆盖其 source stable ledger，再要求所有 component 的
occurrence union 与最终 merged ledger 完全相等。

任何 overlap、gap、source run/ledger 漂移、duplicate occurrence 或 race identity conflict 都失败关闭。coverage
只提供 planning eligibility，不授权 proof、网络或写库。

## 32 批 postprocess frontier

`audit_bulk_stable_id_postprocess_readiness.py` 读取 exact plan、execution ledger 与专用 stable parent。它不会创建
parent，也不会联网或写数据库。对每个 completed receipt，固定查找 `<stable-parent>/<batch-id>`，再重验 stable
manifest、底层 COMPLETE bulk run 和 exact participant occurrence；额外 child、缺失/重复绑定或 source lineage
漂移均失败关闭。

状态只有三种：`waiting_for_bulk_completion`、`stable_postprocess_required`、
`ready_for_global_stable_merge`。最后一种严格要求 32/32 COMPLETE、32/32 stable、`active=null`，并输出 exact
merge input root/SHA 列表。真实账本重放当前为 0/32、active=null，因此仍是 waiting，ledger SHA 保持
`6c83d21a29004b3ec40fb3d060b4701f17fe3cc109a7b8a9adda812f87261c47`。

## 验证

- bulk execution→postprocess→stable→coverage→plan 及相关模块：`19/19`；
- 完整 `runtime/research`（含随后新增的 targeted/global merge/coverage/plan/review frontiers）：`558/558`；
- 相邻 Django identity/module/staging 链：`90/90`；
- change test case IDs：`300/300` 唯一；
- 生产网络请求/数据库写入：`0/0`。

真实 32 批仍等待 event 956 明确释放共享赛事窗口；本桥没有创建 proof、claim、output、budget 或生产 artifact。
