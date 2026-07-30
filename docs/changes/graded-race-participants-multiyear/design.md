# 多年份重赏参赛马采集器设计

## 决策

保留旧脚本 `collect_2026_graded_top5_wikipedia.py`，新增 `collect_graded_race_participants.py`。旧脚本对应已经完成的 2026 前五名 Wikipedia artifact，直接改写会破坏可复现性。

## 流水线

```text
discover
  -> races（可分片、可续跑）
  -> merge_races
  -> profiles（可分片、可续跑）
  -> merge_profiles
  -> finalize
```

网络阶段按对象原子保存 JSON checkpoint，并写 `index.json` 与 `progress.json`。`--time-budget-seconds` 到期时以退出码 75 安全停止；重新运行时使用 `--resume` 跳过终态对象。

## 赛事解析

赛果表中的每一行先规范化 `finish_position_text`：

- 数字：`finished`，保留数字名次。
- DNF、PU、F、UR、BD、DSQ 等：实际出赛，纳入，数字名次为空。
- SCR、NR、withdrawn、未出赛等：未实际出赛，排除。
- 未识别但出现在正式赛果表中的状态：保守纳入为 `unknown_started`，进入后续检查范围，不擅自判断为退赛。

## 地区识别

优先级：

1. `--region-overrides` 中的精确 URL 映射；
2. 精确页面地区标签映射；
3. override 中的地区标签或马场映射；
4. 仅当页面标签为“其他”时，使用保守马场提示；
5. 无法唯一判断则跳过，不做宽泛猜测。

中东聚合阿联酋、沙特阿拉伯、卡塔尔与巴林。

## 马名

马匹档案阶段从公开马匹索引与详情页提取 display/original name：

- 中文名优先使用含汉字且不含假名的 display name；
- 日文名优先使用含假名的 original/display name；
- 英文名优先使用拉丁字符 original name，并移除 `(IRE)` 等产地后缀；
- 不使用 Wikipedia/Wikidata，也不凭空音译。

日本、中国香港以外地区缺少英文名时，记录 `missing_required_english`。finalize 仍产出完整复核文件；使用 `--fail-on-missing-required-english` 可令质量门禁返回非零。

## 输出与兼容

输出文件名包含目标年份，每个 output directory 只绑定一个年份、截止日期和 region override 摘要。不同年份必须使用不同目录，避免 checkpoint 混用。
