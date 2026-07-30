# 单年度分级赛全部参赛马研究设计

## 现状与基线

- 最新干净主线基线：
  `origin/main@6d073dc07cb29201bbc922255923820c872a0467`。
- 旧研究实现：
  `origin/research/2026-graded-top5-wikipedia@c7cb5d7da5f528384d90bcdbeeab37dabf7f01dd`。
- 旧研究分支相对当前主线 ahead 12 / behind 49，不能整体 merge 或把旧状态文档覆盖到主线。
- 实现只移植并改造以下逻辑：StageStore、原子写入、URL allowlist、HttpClient、manifest、
  checkpoint runner、稳定分片、fan-in、synthetic smoke。
- 不移植旧分支对 `current_state`、`project_status` 或旧 change 文档的历史修改。

## 文件布局

预计新增：

- `runtime/research/collect_graded_race_participants.py`
- `runtime/research/test_collect_graded_race_participants.py`
- `runtime/research/README_graded_race_participants.md`
- `.github/workflows/research_graded_race_participants.yml`
- `runtime/research/region_manifests/README.md`

现有 `.codex/scripts/check_workflow_contract.py` 与
`.codex/scripts/test_workflow_contract.py` 仅在新增 workflow 暴露当前合同缺口时做最小兼容修改。

不把旧文件名 `collect_2026_graded_top5_wikipedia.py` 引入主线，避免两个入口和两个 artifact
契约并存。旧研究分支与 PR #24 保持历史 evidence，不原地改写。

## 阶段 DAG

```text
tests/synthetic
       |
     races
       |
  profiles[0..3]
       |
 merge_profiles
       |
    finalize
```

删除 `wikidata_search`、`merge_search`、`wikidata_entities`、`merge_entities`、
`score_horses`、`merge_scores` 六个阶段。`finalize` 只读取已验证的 races 和
merge_profiles index，不创建 HTTP client。

正式阶段：

1. `races`
   - 发现目标年份 sitemap URL。
   - 读取页面、解析范围和全部实际参赛马。
   - 每个 race URL 是一个 checkpoint item；item 保存零或多 occurrence、manifest entry、
     请求计数和结构化状态。
2. `profiles`
   - 按 horse occurrence canonical lookup key 稳定分片。
   - 搜索 UmaFans horse profile 并提取可证明的多语种名称。
   - transport/parse/ambiguous 与“没有 profile”分开。
3. `merge_profiles`
   - 验证四个 shard 的精确覆盖、上游 SHA 和 identity。
   - profile URL 相同的 occurrence 可收敛；名称或 profile 身份冲突拒绝合并。
4. `finalize`
   - 纯离线生成 7 个最终文件及计数不变量。

## 数据模型

### ParticipantRow

替代 `RaceResultRow`：

- race：`region`、`region_label`、`country`、`race_date`、中/原赛事名、grade、racecourse、
  URL、page SHA。
- participant：`horse_number`、`horse_display_name`、`raw_finish_status`、
  `normalized_finish_position`（nullable）、`participant_status`、jockey、trainer、time、margin。
- identity/name：lookup key、profile URL、original、birth year、`name_zh`、`name_ja`、
  `name_en`、`name_completeness`、`name_evidence`。

### HorseNameRecord

按 canonical horse key 汇总：

- occurrence regions/countries、display/original names、profile URLs、birth years。
- 中日英名称与逐字段 evidence。
- `profile_resolution_state`：
  `resolved|not_found|unresolved|ambiguous|error`。
- `required_english_status`：
  `not_applicable|complete|missing`。
- `name_completeness`：`complete|partial`。
- `name_issue_codes`：排序去重数组，可同时记录多个名称/profile 问题。
- occurrence count、graded race count、race contexts。

不保留任何 QID、Wikipedia URL/language/title、match score/status/evidence 或 candidate entity。

## 地区解析

解析顺序：

1. 标准化页面 `race-hero-meta-text` 的首段标签。
2. 若标签唯一映射到八地区，直接使用。
3. 若标签为“其他”，只查询已加载并验证的 region manifest 的 exact canonical race URL。
4. manifest 未命中则返回 `region_unresolved`，该页面不进入范围。
5. 页面精确标签与 manifest 映射冲突时 `permanent_error`，不得选择任一方。

Region manifest schema v1：

```json
{
  "schema_version": 1,
  "year": 2025,
  "classification_complete": true,
  "races": [
    {
      "url": "https://umafans.run/races/2025/example/",
      "region": "middle_east",
      "country": "united_arab_emirates",
      "evidence": "reviewed UmaFans RaceEvent identity"
    }
  ]
}
```

规则：

- year 必须等于 CLI year。
- URL 必须通过 UmaFans HTTPS allowlist、canonical 化并唯一。
- `region` 接受三个新增地区或 `out_of_scope`；中东必须带 allowlisted country，
  `out_of_scope` 仍必须保留审核 country/evidence。
- manifest 自身只提供地区身份，不提供参赛马、等级或名称。
- path 必须解析在 Git worktree 内，regular file，拒绝 symlink。
- 无 manifest 时仍可处理页面已显式展示的全部地区。
- `classification_complete=true` 时，manifest URL 集必须与本年度 sitemap 中所有页面标签为
  “其他”的 canonical URL 集完全相等；缺失、额外或重复均拒绝。只有该全覆盖状态可用于证明
  新地区 `no_public_in_scope_races`。
- `classification_complete=false` 或无 manifest 时，collector 仍处理可直接分类/已列条目，但
  summary 必须输出 `classification_incomplete`、未分类 other URL 数和 exact URL digest。

## 参赛状态解析

结果表第一列先保存原文，再规范化：

- 整数或同着整数：`finished`，保留 nullable numeric position。
- `DNF|PU|F|UR|RO|BD|DSQ` 及中日文受控等价词：保留为对应 `started_non_finish` /
  `disqualified_after_start`。
- `SCR|NR|取消出赛|退赛|除外`：`non_starter`，不纳入 occurrence。
- 未知非空状态：`participant_status=unresolved`，进入结构化复核，不纳入 occurrence，也不
  推断名次或实际起跑。新增状态必须先扩充受控 fixture/词表。

结果行 identity 使用 `(horse_number, normalized horse name)`；同一 race 中完全重复行可幂等
去重，马号相同但马名冲突或 profile URL 冲突为 permanent error。

## 名称提取

名称证据优先级：

1. horse profile 详情页的明确展示名和原名。
2. horse search card 的明确展示名和原名。
3. race result 行的展示名。

字符集仅用于验证候选字段，不用于翻译：

- 中文：含 Han、无 Kana；若同时含拉丁国家后缀，保留完整显示值并另存 normalized identity。
- 日文：含 Hiragana/Katakana。
- 英文：含 Latin 且不是纯中文/日文显示字符串。

一个来源字符串只能归入其证据支持的字段。强制英文地区缺失英文时仍保留 horse row，
`finalize` 把它加入 review queue，并在 summary 分母中报告。英文适用性按 horse 的全部
occurrence regions 求并集：任一强制英文地区命中即 required；中文/日文完整性与英文要求分别
计算，多个 issue code 同时保留。

### `other` profile 身份

- 结果行直接提供的 canonical horse profile URL 可作为主 identity，但仍须验证页面展示名与
  occurrence 名称不冲突。
- 通过 `/horses/?q=` 搜索得到的 `RacingRegion.OTHER` 候选不得因“唯一同名”自动 resolved。
- 搜索候选至少要求规范化原名一致，且出生年或明确 country 之一与 occurrence/race evidence
  一致；country 冲突直接 ambiguous。
- 只有泛化 other 标签、只有一个显示名、缺少额外事实时为 unresolved；horse key 保持
  `target region/country + normalized name`，不同目标地区同名不合并。
- race-region manifest 不得被当作 horse-profile identity evidence。

## 年份与运行身份

`--year` 为所有正式 stage 的 required 参数。run manifest schema 升级并绑定：

- year 与自然年起止；
- target region keys、grade policies、participant status policy；
- region manifest SHA（无 manifest 时为明确的 null marker）；
- race URL list/digest；
- collector source SHA、parser/schema/base commit。

output 根目录推荐：
`runtime/research/output/<year>-graded-race-participants`。

任何 year、region manifest、policy 或工具身份漂移均拒绝 resume。不同年份必须使用不同 output
目录；即使误用相同目录，也由 manifest fail closed。

## Workflow

`workflow_dispatch` inputs：

- `year`：required string，经 shell/CLI 双重校验为四位整数。
- `full_network`：required boolean，默认 false。
- `region_manifest_path`：optional repository-relative path。
- `source_run_id`、`source_attempt`、`source_stage`：三者全空或全有；
  `source_stage` 只接受 `races|profiles`。

PR 只运行离线测试和 synthetic smoke，synthetic 使用固定 year/clock/fixture，不读取真实
region manifest。正式 job 名称和 artifact 名包含 run ID/attempt/stage/shard，year 由每个
artifact 内 manifest 强绑定，不依靠名字作为安全边界。

## 错误与可观测性

- discovery、race page、region、result row、profile lookup、profile detail、name completeness
  分阶段记录。
- transport 错误可重试；结构或身份错误 permanent；缺少必需英文是 review issue，不丢 occurrence。
- summary 分开报告：
  `discovered_urls / fetched_races / included_races / participant_rows /
  unique_horses / non_starters_excluded / participant_status_unresolved /
  required_english_complete / required_english_missing /
  profile_resolved / profile_not_found / profile_unresolved / profile_ambiguous /
  profile_error / errors / request_count`。
- 另报告 `discovered_other_urls / classified_other_urls / unclassified_other_urls /
  out_of_scope_other_urls` 及 URL digest。
- 不把零目标新地区写成采集成功；按地区报告
  `coverage_status=covered|classification_incomplete|no_public_in_scope_races`。
  新地区只有在年度 other URL 全分类后才允许最后一项；否则即使零行也必须是
  `classification_incomplete`。

## 安全、性能和回滚

- 仅允许 UmaFans host；删除 Wikimedia hosts。
- 不导入 Django、不连接数据库、不读生产凭据。
- 每阶段固定请求预算、超时、retry、checkpoint 间隔和 time budget。
- profile 仍稳定四分片；年度规模扩大时不把所有 HTML 常驻内存。
- 回滚是删除新研究入口/workflow 或保持草稿 PR；不会改变旧 PR #24 artifact。
- 本 change 不运行真实公网采集。发布与 full-network run 分别需要最新代码审核后的明确授权。
