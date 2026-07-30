# 年度重赏参赛马采集器

入口：

```text
runtime/research/collect_graded_race_participants.py
```

旧的 `collect_2026_graded_top5_wikipedia.py` 保留用于复现 2026 前五名 Wikipedia artifact；不要混用其 checkpoint。

## 单年运行

下面以 2025 年、4 个分片为例。所有命令使用同一个 output directory：

```bash
OUT=runtime/research/output/graded-race-participants/2025
SCRIPT=runtime/research/collect_graded_race_participants.py

python "$SCRIPT" --stage discover --year 2025 --output-dir "$OUT"

for shard in 0 1 2 3; do
  python "$SCRIPT" --stage races --year 2025 --output-dir "$OUT" \
    --shard-index "$shard" --shard-count 4 \
    --time-budget-seconds 4800 --checkpoint-every 10 --resume
done

python "$SCRIPT" --stage merge_races --year 2025 --output-dir "$OUT" --shard-count 4

for shard in 0 1 2 3; do
  python "$SCRIPT" --stage profiles --year 2025 --output-dir "$OUT" \
    --shard-index "$shard" --shard-count 4 \
    --time-budget-seconds 4800 --checkpoint-every 25 --resume
done

python "$SCRIPT" --stage merge_profiles --year 2025 --output-dir "$OUT" --shard-count 4
python "$SCRIPT" --stage finalize --year 2025 --output-dir "$OUT" \
  --fail-on-missing-required-english
```

退出码 75 表示在 time budget 到期前安全停止。重新执行同一阶段、同一分片并加 `--resume` 即可继续。

## 当前年份

当前年份建议显式指定 cutoff：

```bash
python "$SCRIPT" --stage discover --year 2026 --cutoff 2026-07-30 --output-dir "$OUT"
```

同一 output directory 的所有后续命令必须使用相同的 year、cutoff 和 region override 文件。

## 地区 override

对于 UmaFans 页面仍标记为“其他”、且马场提示不足以可靠判断的赛事，可传入 JSON：

```json
{
  "labels": {
    "澳洲": "australia"
  },
  "racecourses": {
    "Meydan": "middle_east"
  },
  "urls": {
    "https://umafans.run/races/2025/example/": "germany"
  }
}
```

使用：

```bash
python "$SCRIPT" --stage discover --year 2025 \
  --region-overrides runtime/research/graded_participant_region_overrides.example.json
```

override 文件内容的 SHA-256 会绑定到 run manifest；运行中途修改会 fail closed。

## 输出

- `race_participants_<year>.csv`：每场所有实际出赛马。
- `horse_name_mapping_<year>.csv`：按马匹去重后的中、日、英名称。
- `name_review_queue_<year>.csv`：档案未命中、歧义或缺少必备英文名。
- `summary.json`：统计与英文名质量门禁。

数字名次以及 DNF、PU、F、UR、BD、DSQ 等实际出赛状态会纳入；SCR、NR、withdrawn、non-runner 等不纳入。

本工具不访问 Wikipedia/Wikidata，不写生产数据库。
