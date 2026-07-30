# 多年份重赏参赛马采集器规格

## 目标

将既有“2026 年重赏前五名 + Wikipedia 映射”研究工具演进为通用的年度重赏参赛马采集器。旧脚本与旧 artifact 保留用于结果复现；本需求新增独立脚本，不覆盖旧逻辑。

## 运行边界

- 每次运行只处理一个自然年，由 `--year` 指定。
- 默认截止日期为该年 12 月 31 日；当目标年为当前年时，可用 `--cutoff` 指定截至日期。
- 只读取 UmaFans 当前公开且 data-quality-complete 的赛事页和马匹页。
- 不导入 Django model，不写生产数据库，不修改 RaceEvent、RaceEventResult、HorseProfile 或 TermEntry。
- 输出不等于独立证明外部全球赛事目录完整。

## 地区与等级

目标地区：

- 日本
- 中国香港
- 美国
- 英国
- 法国
- 澳大利亚
- 德国
- 中东地区

日本范围：G1/G2/G3、J-G1/J-G2/J-G3、Jpn1/Jpn2/Jpn3。

其余地区范围：G1/G2/G3。

中东地区作为聚合地区，默认识别阿联酋、沙特阿拉伯、卡塔尔、巴林及“中东”标签；对于被 UmaFans 标为“其他”的赛事，只允许通过保守的马场提示或显式 override 映射，不做宽泛猜测。

## 参赛口径

- 纳入所有实际出赛马，而非仅前五名。
- 数字名次全部纳入。
- 未完赛、拉停、堕马、骑师落马、被带倒、失格等已经实际起跑的结果也纳入。
- 退赛、取消出走、未出赛、scratch、withdrawn、non-runner 等不纳入。
- 每条记录保留 `finish_position_text` 与规范化 `result_status`，数字名次另写入可空的 `finish_position`。

## 马名契约

每匹马输出：

- 中文名：尽量补充，可为空。
- 日文名：尽量补充，可为空。
- 英文名：日本和中国香港可为空；其他地区必须具备。

英文名缺失时不得伪造或机器音译，应进入 `name_review_queue_<year>.csv`，并令 summary 的质量门禁失败。

## 输出

- `race_participants_<year>.csv`
- `horse_name_mapping_<year>.csv`
- `name_review_queue_<year>.csv`
- `source_manifest.jsonl`
- `errors.json`
- `summary.json`
- `README.md`

## 非目标

- 不映射 Wikidata 或 Wikipedia。
- 不自动写回术语库或马匹数据库。
- 不处理未公开或 data-quality-incomplete 的赛事页。
- 不在一次运行中跨多个年份。
