# 2026 重赏前五名 Wikipedia 可续跑研究

该工具只读取 UmaFans 公开页与 Wikidata，不导入 Django、不写数据库，也不把研究结果视为权威
马匹身份。输出覆盖口径仍是 UmaFans 当前公开且 data-quality-complete 的 2026 赛事页，不声称
独立证明全球赛事目录完整。

## 安全边界

- PR 默认只执行离线测试和 synthetic sample artifact，不访问公网。
- 完整公网研究只能显式触发 workflow 的 `full_network=true`；本地验收不得运行完整公网采集。
- `finalize` 不构造 HTTP client，只读已验证的 races、merged profiles 和 merged scores index。
- URL 每次请求前及每次 redirect 后都执行 scheme、精确 host、端口和 userinfo allowlist 校验。
- 时间预算在 item/batch 边界停止，退出码 `75` 表示 checkpoint 已安全保存，可重跑恢复。
- 真实 workflow stage 不把 `75` 转为成功：对应 job 保持失败，从而阻止 `needs` 下游消费不完整
  index；checkpoint upload 使用 `if: always()`，失败后仍保留恢复材料。只有后续精确恢复返回
  `0`，DAG 才继续。
- workflow 不使用 attempt 通配下载或 `merge-multiple`。跨 run 恢复必须同时指定唯一
  `source_run_id` 与 `source_attempt`；缺一拒绝，下载后的 manifest/index 身份不兼容也拒绝。

## 目录与 checkpoint

每个 item 使用 key 的 SHA-256 作为文件名，JSON 内保留原 key。正式 JSON、CSV、JSONL 和 README
均在同目录写临时文件，经 `flush`、`fsync` 和 `os.replace` 原子替换。每个阶段或 shard 都有
独立的 `progress.json` 与 `index.json`；index 绑定排序后的 key、相对路径、状态、内容 SHA-256
及汇总 SHA。临时文件不会被 index 或 merge 读取。

每个 index 还冻结真实 manifest SHA、按 stage 命名的全部上游 index SHA、计划输入 key digest、
collector/parser/scorer/schema/base commit 身份和该网络阶段的累计实际 request count。resume、
merge、finalize 会重算 item、manifest、输入与上游链；任一漂移均 fail closed。

根目录 `run_manifest.json` 冻结 year、cutoff、base URL、race URL 清单及摘要、collector 源码
SHA、parser/scorer/schema version 和基线 commit。resume 遇到 tool、输入或 shard 参数漂移会
fail closed，不覆盖旧 run。

## 阶段命令

以下示例只说明接口，不授权联网执行：

```bash
OUT=runtime/research/output/2026-graded-top5-wikipedia

python runtime/research/collect_2026_graded_top5_wikipedia.py \
  --stage races --resume --checkpoint-every 20 --time-budget-seconds 3600 \
  --base-url https://umafans.run --cutoff 2026-07-26 --output-dir "$OUT"

for shard in 0 1 2 3; do
  python runtime/research/collect_2026_graded_top5_wikipedia.py \
    --stage profiles --resume --shard-index "$shard" --shard-count 4 \
    --checkpoint-every 25 --time-budget-seconds 3600 --output-dir "$OUT"
done
python runtime/research/collect_2026_graded_top5_wikipedia.py \
  --stage merge_profiles --shard-count 4 --output-dir "$OUT"

for shard in 0 1 2 3; do
  python runtime/research/collect_2026_graded_top5_wikipedia.py \
    --stage wikidata_search --resume --shard-index "$shard" --shard-count 4 \
    --checkpoint-every 25 --time-budget-seconds 4500 --output-dir "$OUT"
done
python runtime/research/collect_2026_graded_top5_wikipedia.py \
  --stage merge_search --shard-count 4 --output-dir "$OUT"

for shard in 0 1 2 3; do
  python runtime/research/collect_2026_graded_top5_wikipedia.py \
    --stage wikidata_entities --resume --shard-index "$shard" --shard-count 4 \
    --checkpoint-every 25 --time-budget-seconds 3600 --output-dir "$OUT"
done
python runtime/research/collect_2026_graded_top5_wikipedia.py \
  --stage merge_entities --shard-count 4 --output-dir "$OUT"

for shard in 0 1 2 3; do
  python runtime/research/collect_2026_graded_top5_wikipedia.py \
    --stage score_horses --resume --shard-index "$shard" --shard-count 4 \
    --checkpoint-every 25 --time-budget-seconds 900 --output-dir "$OUT"
done
python runtime/research/collect_2026_graded_top5_wikipedia.py \
  --stage merge_scores --shard-count 4 --output-dir "$OUT"
python runtime/research/collect_2026_graded_top5_wikipedia.py \
  --stage finalize --output-dir "$OUT"
```

所有网络阶段还支持 `--start-index`、`--limit`。稳定 shard 归属为
`int(sha256(canonical_key), 16) % shard_count`，不使用 Python `hash()`。

## 离线 synthetic smoke

PR 与 tests job 会真实运行同一 collector 的 `synthetic_smoke`：第一次在 item 边界返回 `75` 并
保留 `safe_stop.json` 和 stage checkpoint；第二次从该 checkpoint 恢复，依次执行 profile、
search、entity、score fan-in 与纯离线 finalize，再与不中断基线比较 checkpoint item bytes。
上传 artifact 的是 `run_manifest.json`、`safe_stop.json`、`stages/`、`final/` 和 smoke report，
不是测试源码占位文件。

## 身份与错误语义

- race 行优先使用 `region|source_host|source_identity` lookup key；无 profile identity 时使用
  `region|normalized_name`，赛事 URL、日期和赛事名只作为 occurrence evidence。
- profile shards 完成后，全局 merge 以唯一 profile URL 收敛 canonical horse；同内容重复可
  幂等去重，冲突和覆盖不完整会拒绝合并。
- Wikidata search 必须保存每个计划 query/language 的成功或失败。只有全部请求成功且零候选
  才能产生 `no_page`。
- entity shard 按 QID 拥有 cache；score shard 按 canonical horse key 拥有马匹，并从 merged
  entity cache 读取完整候选集。
- profile/search/entity transport 或缺失错误产生 `resolution_state=error`，匹配状态留空并进入
  review queue。最终计数满足：
  `exact + probable + ambiguous + no_page + resolution_error = unique_horse_seeds`。
- `finalize` 汇总 races、profiles、search、entities 与 scores 的结构化错误，`errors.json` 条数、
  `summary.source.all_errors` 和 resolution-error review queue 使用同一冻结输入；实际请求数由
  races/profile/search/entity index 聚合，不再写死为 `0`。
- 身份证据不足的 fallback seed 即使分数很高也不能自动成为 `exact`。

## 最终文件

`final/` 包含：

- `race_top5_2026.csv`
- `horse_wikipedia_mapping_2026.csv`
- `wikipedia_review_queue_2026.csv`
- `source_manifest.jsonl`
- `summary.json`
- `errors.json`
- `README.md`
