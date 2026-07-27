# 2026 重赏前五名 Wikipedia 映射可续跑改造规格

## 背景

PR #24 已具备公开赛事页解析、马匹页补全、Wikidata 候选搜索、实体评分和最终文件生成逻辑。
2026-07-26 的两次完整 GitHub Actions 运行都采到 456 场赛事、2231 条前五名记录和 1540
个马匹身份种子，但在 Wikidata 搜索约 700/1540 时到达 180 分钟 job 上限。现有脚本在
进程末尾才创建正式输出，导致取消后没有可下载 checkpoint。

## 目标

- 把单进程流水线拆成 `races`、`profiles`、`wikidata_search`、
  `wikidata_entities`、`finalize` 五个可单独运行阶段。
- 每个网络阶段按 item 或小批次原子保存 checkpoint，并支持安全续跑。
- 支持稳定分片、确定性合并、时间预算、范围限制和周期进度。
- GitHub Actions 在每阶段保留 artifact；一个分片失败不删除其他成功分片。
- `finalize` 只读前序 checkpoint，不访问网络，生成全部约定文件。
- 保留现有保守匹配状态；网络失败不得被降格成 `no_page`，歧义不得强制 exact。

## 功能要求

### 阶段与恢复

1. `races`
   - 冻结发现的赛事 URL 清单和输入参数。
   - 每个 URL 保存成功、跳过或错误结果；成功结果包含页面 SHA、正式名次行和来源证据。
   - `--resume` 时跳过已完成 item；可重试明确标记为 retryable 的错误。
2. `profiles`
   - 从赛事 checkpoint 构造不可变 `lookup_key`：有来源 horse identity/profile href 时使用
     `region|source_identity`；否则使用 `region|normalized_name`。赛事 URL、名称和日期只作为
     occurrence evidence，不进入 key，避免同马跨赛事被拆分。
   - 所有 profile shard 完成后执行全局 `merge_profiles`：优先按唯一 profile URL 形成
     `canonical_horse_key`；多个 lookup key 收敛到同一 URL 时合并来源证据，冲突时转人工歧义。
   - 后续搜索分片只能使用 merge 后冻结的 `canonical_horse_key`，不得在 shard 内再次改 key。
   - 每匹马保存独立结果；缓存命中不得发起网络请求。
3. `wikidata_search`
   - 每匹马保存候选搜索结果与请求状态。
   - 任一计划 search 请求失败时保存 `retryable_error`，不得评分或生成四类匹配状态；
     只有全部计划请求成功后，零候选才可生成 `no_page`。
4. `wikidata_entities`
   - 对 QID 固定排序、分批抓取实体，并在每批后保存；同一 QID 全 run 只需一份实体 cache。
   - 实体 shard 仅拥有 QID 抓取；合并实体 cache 后，评分 shard 按 `canonical_horse_key`
     拥有马匹，并读取该马全部候选 QID，禁止用不完整候选集评分。
   - 评分结果按马匹保存；相同输入产生相同排序与状态。
5. `finalize`
   - 校验输入 manifest、分片覆盖、重复 key 和冲突。
   - 只从 checkpoint 生成最终 CSV/JSON/README，不访问网络。

### CLI

提供等价能力：

- `--stage`
- `--resume`
- `--start-index`
- `--limit`
- `--shard-index`
- `--shard-count`
- `--time-budget-seconds`
- `--checkpoint-every`

时间预算只允许在 item 或 batch 边界停止，并返回可识别的安全停止状态。

### 持久化与确定性

- 正式 checkpoint 和最终文件必须在同目录临时文件写入、flush、`fsync`、关闭后
  `os.replace`。
- `progress.json` 至少包含阶段、已处理/总数、成功/失败数、最后对象、更新时间、耗时。
- 稳定分片使用 canonical key 的 SHA-256，不使用 Python `hash()`。
- 合并前检测重复 key；同内容可幂等去重，内容冲突必须 fail closed。
- set、dict、候选、证据和输出行必须显式排序。
- manifest 绑定 schema/tool version、base URL、cutoff、输入摘要和分片参数；恢复时漂移拒绝。
- 每个 stage index 保存按 key 排序的 item path、状态、内容 SHA-256 及其汇总 SHA，并冻结
  run manifest 文件 SHA、全部具名上游 index 文件 SHA、完整计划输入 key digest、tool identity
  与累计实际 request count；resume、merge、finalize 读取时逐项重算和核对。
- tool version 绑定 collector 源码 SHA、parser/scorer/schema version 与基线 commit。

### 可观测性

- 赛事每 10—25 个、马匹每 25—50 个、Wikidata entity 每批输出一次进度。
- 日志包含阶段、数量、成功/失败、耗时、速度和粗略 ETA，并立即 flush。
- 每次保存输出 `CHECKPOINT_SAVED path=...`。
- 各阶段 artifact 包含 `progress.json` 和 manifest。

### 最终输出

- `race_top5_2026.csv`
- `horse_wikipedia_mapping_2026.csv`
- `wikipedia_review_queue_2026.csv`
- `source_manifest.jsonl`
- `summary.json`
- `errors.json`
- `README.md`

`summary.json` 必须报告入围赛事、前五名记录、去重马匹、各地区赛事、四类匹配状态和错误数，
并明确覆盖仅基于 UmaFans 当前公开且 data-quality-complete 的赛事页。

网络或解析错误使用独立 `resolution_state` / `error_code`。错误马匹的
`wikipedia_match_status` 留空并进入 review queue；满足：

```text
exact + probable + ambiguous + no_page + resolution_error = unique_horse_seeds
```

profile lookup、每次 Wikidata search、每个 QID entity 都保存成功/失败状态，错误不可被默认值覆盖。
任一候选 QID 未达到成功终态时不得评分；重试补齐后才重新产生四类状态。

## 非目标

- 不导入 Django model，不写 UmaFans 数据库。
- 不修改 `RaceEvent`、`RaceEventResult`、`HorseProfile` 或 `TermEntry`。
- 不在生产服务器运行长抓取，不部署、重启或修改生产容器。
- 不把研究匹配结果直接作为权威马匹身份。
- 不合并 PR #24 到 `main`。
- 本轮不独立证明全球外部赛事目录完整。

## 验收标准

- 离线自动化测试覆盖规格中的恢复、幂等、分片、原子写、错误状态和最终字段。
- 小样本端到端成功；人为中断后 resume 与不中断基线一致。
- workflow 至少能上传一个阶段 checkpoint artifact。
- tests job 必须真实执行 synthetic `safe stop(75) -> resume -> 四级 fan-in -> finalize`，并上传
  实际 `run_manifest/index/items/progress/final` 证据；测试源码本身不算 checkpoint artifact。
- 真实 races/profile/search/entity/score stage 返回 `75` 时 job 必须保持失败以阻止下游；其
  checkpoint upload 仍须 `if: always()` 执行。只有恢复后返回 `0` 才满足 downstream 门禁。
- 任一长阶段不会因单个 job 超时使既有成果归零。
- 全部实现通过未参与实现的 reviewer 独立审核。
