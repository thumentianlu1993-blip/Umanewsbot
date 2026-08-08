# 2025 单年度分级赛全部参赛马正式运行报告

## 结果

GitHub Actions run `31269803408` 以 `year=2025`、`full_network=true` fresh start；tests、races、
四个 profile shards、merge_profiles 与 finalize 全部 success。未使用 checkpoint continuation，
本轮消耗最多六次运行额度中的 `1` 次。

运行地址：<https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/31269803408>

## 最终 artifact

- 名称：`31269803408-1-finalize-0`
- artifact ID：`9025592068`
- 大小：`799594` bytes
- digest：`sha256:ef8bbc107379413aa2e2ca8ed0dc144759fb7b3578b4d15746b421b923477535`
- 严格文件集合：`README.md`、`errors.json`、`horse_name_review_queue_2025.csv`、
  `horse_names_2025.csv`、`race_participants_2025.csv`、`source_manifest.jsonl`、`summary.json`

## 数据审核

- `outcome=partial`
- discovered/fetched/included races：`1063/1063/1063`
- participant rows：`9292`
- unique horses：`4965`
- request count：`6982`
- profile resolved/not found/ambiguous/unresolved：`920/3998/32/15`
- required English complete/missing：`2/3905`
- France、Hong Kong、Japan、UK、US：`covered`
- Australia、Germany、Middle East：`classification_incomplete`

这是成功生成的可审计 partial artifact，不是八地区完整语料。剩余项属于确定性来源分类、名称和
profile 资料缺口，不是临时网络失败或 exit 75；因此不使用剩余五次额度重复相同输入。
