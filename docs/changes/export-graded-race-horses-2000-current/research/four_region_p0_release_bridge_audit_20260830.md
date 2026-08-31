# 四地区 participant 到 P0 release 桥审计

日期：2026-08-30（Asia/Shanghai）
状态：本地合同完成；无真实 candidate、approval 或 production apply
外部副作用：`0` TRA 请求、`0` 数据库写入、`0` production 变更

## 结论

现有链已能承接本 change 的多年四地区 actual starters：

```text
materialized TRA horse artifact
  -> racing-api-horse-p0-candidate.v1
  -> exact module-review proposal/approval
  -> reviewed research + authority manifest
  -> existing profile mapping bundle
  -> reviewed P0 completion artifact
  -> existing dry-run / shared HorseRaceRecord upsert / receipt / verifier
```

`target_scope` 独立保存 event region，不使用 horse home region 过滤。新增覆盖证明下列边界都能经过
module-review approval 后进入与现有 P0 validator 兼容的 research contract：

- GB：2000 G1；
- France：2020 G1；
- Ireland：2021 G3；
- USA：2024 G2。

每个 occurrence 保留 `rac_*`、race date、event region、当届 grade 和 actual-start participant status；
career record 的 `race_region` 与 target event region 一致。1999 G1 和 2020 G2 继续在 module review 前
失败关闭。

## 共享产品写链

`prepare_reviewed_p0_completion_artifact` 已把同一审核行拆成：

- `profile_payload`；
- `pedigree_payload`；
- `race_records_payload`；
- `major_wins_payload`；
- aliases、career history、module reviews 和证据链。

正式 commit 没有新增 TRA 专用直写：它继续调用 `apply_reviewed_completion_artifact`，由共享
HorseRaceRecord normalization/upsert、manual-lock、completion run、source metadata、strict completeness
和 receipt/verifier 负责。网络 runner 与这条写链保持分离。

## 本轮修正

审计发现 `major_wins_payload` 旧筛选条件是 `result_status=won OR is_major_win`，会把普通胜场带进“主胜鞍”
审核模块，也允许仅有标记但并非获胜的记录进入。现改为同时满足：

- `result_status=won`；
- `is_major_win is True`。

TRA candidate 的 `is_major_win` 只在 finish=`1/1DH` 且当届 grade 为 G1/G2/G3 时生成，因此现在与规格
J06 一致。普通胜场仍完整保留在 `race_records_payload`，只是不再冒充主胜鞍。

## 验证

- module review + P0 production apply 聚焦：`41/41`；
- profile candidate/module review/P0 apply/participant release/completion adapters/participant batch/career
  history 组合：`131/131`；
- Django system check、py_compile、`git diff --check`：通过。

透明保留一次无效调用：组合回归最初包含不存在的 `stable.test_p0_horse_profiles`，真实加载的 48 个测试
通过但命令整体有 1 个 loader error，不能作为绿色证据；随后改用仓库实际模块重跑上述 `131/131`。

这些结果关闭 tasks 5 中的 participant release 与四个产品模块实现项，但不关闭 production release
manifest、PostgreSQL concurrency/rollback、backup、用户写授权或页面验收。
