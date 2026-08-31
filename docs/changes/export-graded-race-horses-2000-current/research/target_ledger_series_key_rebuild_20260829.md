# 目标账本跨年份 series key 重建审计

> 后续 AQPS discipline/surface 语义修正已发布新的 PREPARED target；本文件中的 ledger/manifest SHA
> 仅保留为 series-key 历史差分证据，不得作为当前 seed 或 TRA 请求输入。当前身份见
> `target_ledger_aqps_correction_20260829.md`。

日期：`2026-08-29`

状态：`PREPARED / NO DATABASE WRITE`

## 结论

`build_graded_horse_target_ledger.py` 原来逐年调用 TJCIS parser 后直接汇总，没有在 27 个年份全部加载后
再次调用既有的全局同名赛事消歧器。结果是同一系列可能在早年使用短 key、近年因出现同名赛事而改用带
马场/赛制/距离的长 key。这个问题不会改变赛事事实行数量，但会破坏跨年份 series identity，并使别名
审核、occurrence 提案和下游 artifact 绑定漂移。

修复后，构建器先汇总全部年份，再调用 `_global_disambiguate_ambiguous_series(rows)`，最后才做来源冲突
审核与账本编译。回归测试用两个年份的 fake parser 证明消歧器只调用一次、看到全部年份行，且在输出前
完成。

## 重建身份

- root：`/Users/mentianlu/.codex/umanews-target-seriesfix-20260829.L1aF64/output`
- target rows：`12,047`
- target ledger SHA-256：
  `f04a7d5886c91de9c300598cd9d752b48960342ca6d334bdb75c2e3edef69481`
- manifest SHA-256：
  `c3675dd1349d3de7864f986cf101a5fdb5daa352ce533e6da4b7dc102719bf19`
- marker/status：`PREPARED / needs_source_conflict_review`
- 范围 blocker：`9`
- blocker canonical payload SHA-256：
  `dedf39dff4fb4a342dd3737fa7d096e7c9d641598dd5847ec7f5558e9495d9d1`

构建在 Docker `--network none` 下运行；输入为既有 2000–2026 TJCIS 冻结缓存及其 source manifest，
没有下载、付费 API 请求或数据库写入。

## v2 到新版差分

把两版每行的 `series_key`、`target_key` 和仅表示本机位置的 `source.cache_path` 排除后，对其余全部事实
字段做 multiset 比较：

| 指标 | 结果 |
|---|---:|
| v2 rows | 12,047 |
| 新版 rows | 12,047 |
| 事实行删除 | 0 |
| 事实行新增 | 0 |
| series/target key 改变 | 226 |
| 英国 key 改变 | 139 |
| 美国 key 改变 | 87 |
| 法国/爱尔兰 key 改变 | 0 |

上述比较已由通用只读审计器 `audit_graded_horse_target_rebuild.py` 重放并冻结：

- audit root：`/Users/mentianlu/.codex/umanews-target-seriesfix-audit-20260829`
- audit manifest SHA-256：
  `a4598953523162c5ac360b2a928bce10adf14b53b4cd61cada2f505a4bd8f731`
- 226 行 key change ledger SHA-256：
  `88bde45a155fa066e5a843d156caa993390ba63f42ae5f48ef8171f89eff79ea`
- marker/status：`AUDITED_REFERENCE_ONLY / fact_equivalent_key_migration`
- `approval=false`、`database_writes=0`

典型修正包括：

- 英国 Ascot flat `Gold Cup` 统一为
  `united-kingdom-gold-cup-ascot-flat-20-turf`；
- 英国 Cheltenham G1 `Stayers’ Hurdle` 统一为
  `united-kingdom-stayers-hurdle-cheltenham-jumps-3-jumps`；
- 美国 `First Lady`、`Matron`、`Ack Ack` 等同名系列按马场、赛制、距离或场地消歧；
- 既有 key 尾部不再把当届 grade 当作系列身份，从而避免升降级时无必要地拆分 series。

## 下游重审

新版账本重新运行旧历史 detail bundle 审计，数量与旧版完全守恒：

| bundle | exact occurrences | actual starter rows | manual alias |
|---|---:|---:|---:|
| 英国 Sporting Life v8 | 186 | 1,683 | 11 / 111 rows |
| 法国 ZEturf base | 113 | 730 | 0 |
| 法国 ZEturf correction | 2 | 12 | 0 |

11 个英国 alias 仍需独立审核，但建议 key 必须改为新版身份并绑定新版 target manifest。2015 Finale
跨年补赛提案也已从冻结 Sky/RTE 缓存零网络重建，仍是 8 匹 actual starters，状态保持
`PREPARED/awaiting_review`。

## 门禁

- 旧 v2 target、旧 audit、旧 alias 建议和旧 Finale proposal 全部只保留为历史证据，不可执行。
- 9 个 source conflict 的 payload SHA 虽未改变，仍需要真实独立审核人签署；研究者不能自我审批。
- 只有新账本经过 review 后成为 `COMPLETE`，下游 audit/alias/cross-year evidence 全部重新绑定，才可生成
  runnable occurrence seeds。
- 本次聚焦纯离线组合在加入重建差分审计器后为 `59/59`；`compileall`、diff check 另在最终验证记录中
  列出。
