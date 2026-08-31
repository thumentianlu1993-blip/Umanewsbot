# 最终 global stable merge 来源策略

## 唯一来源集合

最终 graded-horse occurrence merge 只接受：

- 32 个 2005+ bulk stable ledgers；
- 65 个 pre-2005 targeted stable ledgers。

合计恰好 97 个 source ledgers。France/Ireland 13 马 stable pilot 与其 held/external pilot components 不进入最终
occurrence merge，因为相同 target 会被完整 2005+ bulk partition 正式覆盖；再次加入会形成重复 horse/race/target
occurrence。pilot 已取得的 enrichment bytes 只能在后续 exact provider-ID staging/replay 规则下复用，不能成为第二份
occurrence authority。

## 组合门禁

`audit_global_stable_id_merge_readiness.py` 只读调用两个 partition frontier。只有 bulk 32/32、targeted 65/65、
两个 execution ledger 均 inactive 时，才返回 `ready_for_exact_global_merge`、97 个唯一 root/SHA 和完整 merger argv。
任一 denominator 漂移、source count 漂移、重复 root/SHA 或预先存在的 output 目录都失败关闭。

merge 完成后，`audit_global_stable_id_coverage_readiness.py` 再重验 merged v2 manifest 的 exact 97-source set，并
生成唯一 coverage argv：32 个 provider-native bulk runs + 65 个 provider-native targeted materializations。任何
source 缺/多/漂移或 pilot component 混入都停止。

coverage COMPLETE 后，`audit_global_stable_id_enrichment_plan_readiness.py` 会第三次绑定同一 source frontiers、
merged v2 与 coverage root/SHA；只有 97 个 components 恰为 32 bulk +65 targeted、全部 occurrences 与 unique
`hrs_*` 守恒时，才输出 zero-search planner argv。coverage COMPLETE 不能作为手工拼 planner 参数的捷径。

真实重放当前为：

- bulk `waiting_for_bulk_completion / 0 of 32`，ledger SHA `6c83d21a…61c47`；
- targeted `waiting_for_targeted_completion / 0 of 65`，ledger SHA `8f9d51cc…6a50d`；
- global `waiting_for_source_partitions / ready 0 of 97`；
- merge argv：`null`；
- enrichment plan readiness：exit 75，`authoritative source partitions are not globally merge-ready`；
- 网络/数据库写：`0/0`。

两个 execution ledger SHA 保持 `6c83d21a…61c47 / 8f9d51cc…6a50d`；merge、coverage、plan future roots 均
absent。完整 research `558/558`，相关链 `28/28`，test case IDs `300/300` 唯一。该门禁不改变 event 956 暂停边界。
