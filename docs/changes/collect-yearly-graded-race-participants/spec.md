# 单年度分级赛全部参赛马研究规格

## 背景

现有研究流水线只存在于未合并的
`research/2026-graded-top5-wikipedia@c7cb5d7d`，固定采集 2026 年五个地区已完赛分级赛的
前五名，再执行 Wikidata/Wikipedia 搜索、实体解析和评分。当前主线不包含该 collector 或
workflow。

本 change 将可复用的 checkpoint、manifest、稳定分片和 artifact DAG 带入最新主线，同时把
业务目标改为：一次显式采集一个年份、覆盖八个地区的分级赛全部实际参赛马、输出保守的中日英
马名，不再访问或映射 Wikipedia/Wikidata。

## 目标

1. 每次 run 必须显式指定且只处理一个自然年。
2. 从 UmaFans 当前公开、`data-quality-complete` 的已完赛分级赛页面提取全部实际参赛马，
   不再限制名次 1—5。
3. 地区覆盖日本、中国香港、美国、英国、法国、澳大利亚、德国和中东。
4. 为每匹去重马输出中文名（尽力）、日文名（尽力）和英文名；美国、英国、法国、澳大利亚、
   德国和中东的英文名为强制完整性字段，日本和中国香港的英文名允许为空。
5. 删除全部 Wikipedia/Wikidata 网络、阶段、字段、评分、复核状态和输出文件。
6. 保留可验证、可安全停止、可跨精确 run 恢复的 artifact-only 研究边界。

## 范围

### 年份

- CLI 的 `--year` 为必填整数，不提供 2026 默认值。
- 支持 `1984 <= year <= 当前 UTC 年份`。
- 一个 run manifest 只能绑定一个年份；不同年份不得共用 checkpoint。
- 历史年份处理完整自然年。当前年份仍只接收页面状态为“已结束”或“已完赛”的赛事，不把
  未来或进行中赛事算入。
- `--cutoff` 从正式接口移除；测试用固定 clock 控制当前年份上界。

### 地区与等级

规范地区：

| key | 显示名 | 接受的公开页标签 |
| --- | --- | --- |
| `japan` | 日本 | 日本 |
| `hong_kong` | 中国香港 | 中国香港、香港 |
| `united_states` | 美国 | 美国 |
| `united_kingdom` | 英国 | 英国 |
| `france` | 法国 | 法国 |
| `australia` | 澳大利亚 | 澳大利亚、澳洲 |
| `germany` | 德国 | 德国 |
| `middle_east` | 中东 | 中东、阿联酋、沙特阿拉伯、沙特、卡塔尔、巴林 |

- 日本接受 G1/G2/G3、J-G1/J-G2/J-G3、Jpn1/Jpn2/Jpn3。
- 其他七个地区接受 G1/G2/G3 的常见罗马数字、`Grade`、`Group` 表达，经既有规范化逻辑
  收敛。
- 中东 v1 的国家集合固定为阿联酋、沙特阿拉伯、卡塔尔和巴林；不得把赞助商、赛事名中的
  国家词或马场名当作地区证据。
- 当前主线 `RacingRegion` 会把新地区显示为“其他”。为避免猜测，collector 支持可选的
  `--race-region-manifest <path>`，逐项以完整 canonical race URL 指定
  `australia|germany|middle_east|out_of_scope` 和 country。manifest 必须是仓库内 regular
  JSON、无 symlink、无重复 URL，内容 SHA-256 写入 run manifest。
- 页面已经给出精确新地区标签时无需 override；页面只给“其他”且没有 manifest 条目时跳过，
  记录 `region_unresolved`，不得按 URL slug、赛事名或马场猜测。
- manifest 只有在声明 `classification_complete=true`，且条目 exact 覆盖本年度 sitemap 中
  全部“其他”页面 URL 时，才可证明年度分类完整；否则新地区零结果只能写
  `classification_incomplete`，不得写“没有公开范围内赛事”。

### “参赛马”语义

- 来源是已完赛赛事页面的正式结果表，而不是赛前出马表。
- 结果表中每个具有马名、且状态不是退赛/取消出赛/non-runner 的条目均算实际参赛。
- 数字名次、同着、未完赛、落马、拉停、赛后取消资格等只要实际起跑均保留。
- 退赛、取消出赛和只出现在赛前出马表但没有实际起跑证据的马不计入。
- 未纳入受控状态词表的非空状态为 `participant_status=unresolved`，不计入 occurrence 并进入
  复核；不得仅因它出现在结果表就推断已经起跑。
- 不要求恰好五行、连续名次或全部为数字名次；同一赛事的参赛 identity 冲突仍 fail closed。
- 每个 occurrence 保存原始名次/状态文本、规范化 participant status、马号、骑师、练马师、
  时间、差距、赛事 URL 与页面 SHA。

### 马名语义

- 只使用 UmaFans 公开赛事页、马匹搜索页和马匹详情页；不访问 Wikipedia、Wikidata 或其他
  外部名称服务。
- `name_zh`：优先使用明确的中文展示名；无法取得时允许为空并进入名称复核队列，禁止自动
  音译。
- `name_ja`：只接受明确包含日文假名/日文原名字段的证据；无法取得时允许为空。
- `name_en`：只接受明确拉丁字母原名/英文名。日本、中国香港允许为空；其余六个地区为空时
  `required_english_status=missing`，保留 occurrence 但进入复核队列，最终 summary 不得宣称
  名称完整。只要一匹马在任一强制英文地区有 occurrence，即适用该要求。
- `required_english_status=not_applicable|complete|missing` 与
  `name_completeness=complete|partial` 分开；`name_issue_codes` 可同时包含
  `missing_chinese`、`missing_japanese`、`missing_required_english`、profile 问题等多个代码。
- 同一个字符串不得仅凭字符集同时填入多个语言字段。
- 去重优先使用 canonical UmaFans horse profile URL；没有 profile identity 时使用
  `region + normalized display/original name`。同名多 profile、跨地区冲突或一个 occurrence
  对应多个 profile 时保持独立错误，不强行合并。
- 对澳大利亚、德国和中东，公开 profile 的泛化 `RacingRegion=other` 不是身份匹配证据。
  只有结果行直接携带可验证 profile URL，或候选的原名加出生年/国家等额外事实与 race country
  一致时才可 resolved；唯一同名搜索结果本身不足，必须保持 unresolved。region manifest 只证明
  race 地区，不证明 horse profile 身份。

## 输出

`final/` 固定包含：

1. `race_participants_<year>.csv`：赛事—实际参赛马 occurrence。
2. `horse_names_<year>.csv`：年度去重马与中日英名称。
3. `horse_name_review_queue_<year>.csv`：中文缺失、必需英文缺失、profile
   unresolved/ambiguous/error。
4. `source_manifest.jsonl`：所有已请求赛事页的 URL、状态、地区、日期、等级、抓取时间与 SHA。
5. `summary.json`：年份、地区/等级、赛事/occurrence/去重马/名称完整性/错误/请求计数。
6. `errors.json`：结构化发现、赛事解析、profile 解析与名称完整性错误。
7. `README.md`：范围、字段和覆盖警告。

以下旧文件不得再生成：

- `race_top5_2026.csv`
- `horse_wikipedia_mapping_2026.csv`
- `wikipedia_review_queue_2026.csv`

## 不变量

- `included_participant_rows` 等于 occurrence CSV 数据行数。
- `unique_horses` 等于 horse names CSV 数据行数。
- `required_english_complete + missing_required_english` 等于六个强制英文地区的去重马数。
- 上述分母按 horse key 去重；一匹马只要参加过任一强制英文地区赛事就计入一次。
- review queue 的 horse key 唯一，且只包含可解释的名称/profile 问题。
- `profile_resolved + profile_not_found + profile_unresolved + profile_ambiguous +
  profile_error` 等于 unique horses。
- 每个 included race 至少一匹实际参赛马；无实际参赛条目的已完赛范围内赛事为解析错误。
- `result_rows_with_horse = included_participant_rows + non_starters_excluded +
  participant_status_unresolved`，完全重复行的去重数另列且不得破坏守恒。
- run manifest 的 year、region policy、grade policy、region manifest SHA、race URL digest、
  collector source SHA、parser/schema/base commit 与 checkpoint 完全一致。

## 非目标

- 不修改 Django model、`RacingRegion`、生产页面或生产数据。
- 不自动翻译/音译马名。
- 不证明 UmaFans 之外的全球分级赛目录完整。
- 不采集普通赛、Listed 或未分级赛事。
- 不执行完整公网 run、提交、推送、创建 PR、部署或生产写入；这些保留为后续独立授权。

## 验收标准

- 离线 fixture 覆盖八地区、历史年份、可变参赛数、同着、非完赛状态与退赛排除。
- 未知状态不计入参赛；英文满足但中文缺失、同马多个 issue、跨地区英文适用性均有独立断言。
- 新地区唯一同名 `other` profile、国家不符与跨目标地区同名均保持 unresolved。
- region manifest 完整/不完整两种年度分类均有 URL 覆盖守恒；不完整时禁止输出
  `no_public_in_scope_races`。
- 任意两个不同年份的 checkpoint 互相恢复时明确拒绝。
- 旧 Wikipedia/Wikidata host、类、阶段、workflow job、字段和输出名在新实现中均不存在。
- PR/default workflow 只跑离线测试与 synthetic artifact；正式网络阶段仅在显式
  `workflow_dispatch full_network=true` 时执行。
- safe-stop 仍以退出码 75 阻断下游并上传精确 checkpoint；恢复只接受同 year、同 tool identity
  的 `source_run_id + source_attempt + source_stage`。
