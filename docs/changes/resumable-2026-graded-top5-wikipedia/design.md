# 设计：可续跑的分阶段研究流水线

## 设计原则

保持现有解析和评分业务逻辑，新增薄的阶段编排、稳定序列化和 checkpoint 层。正式 checkpoint
是流水线事实来源；内存对象只是当前 item 的工作状态。

## 目录合同

```text
<output-dir>/
  run_manifest.json
  progress_summary.json
  stages/
    races/items/<key>.json
    races/progress.json
    races/index.json
    profiles/shards/<n>/items/<key>.json
    profiles/shards/<n>/progress.json
    profiles/shards/<n>/index.json
    profiles/merged/items/<canonical-horse-key>.json
    profiles/merged/index.json
    wikidata_search/shards/<n>/items/<key>.json
    wikidata_search/shards/<n>/progress.json
    wikidata_search/shards/<n>/index.json
    wikidata_entities/shards/<n>/entities/<qid>.json
    wikidata_entities/shards/<n>/progress.json
    wikidata_entities/shards/<n>/index.json
    wikidata_entities/merged/entities/<qid>.json
    wikidata_entities/merged/index.json
    scored_horses/shards/<n>/items/<canonical-horse-key>.json
    scored_horses/shards/<n>/progress.json
    scored_horses/shards/<n>/index.json
  final/
    ...
```

文件名 key 使用 canonical identity 的 SHA-256；JSON 内保留原 key，避免文件名反推身份。
根级 `progress_summary.json` 只由 merge/finalize 从冻结 shard index 重建；网络 shard
不得写它。续跑事实来源是各 stage/shard 自己的 `progress.json`。

## Manifest 与输入冻结

首次 `races` 创建 `run_manifest.json`，字段包括：

- `schema_version`
- `tool_version`
- `year`
- `cutoff`
- `base_url`
- `race_urls` 和 `race_urls_sha256`
- `collector_source_sha256`
- `parser_version`、`scorer_version`、`schema_version`
- `base_commit`
- `created_at`

后续阶段在自己的 index 中记录所有具名上游 index SHA-256、run manifest 文件 SHA-256、完整
计划输入 key digest、shard 参数、tool identity、累计实际 request count 和自身输出摘要。`--resume`
若发现已存在 manifest 与 CLI 参数不一致则退出，不覆盖旧 run。

每个 index 内含按 key 排序的 `items[]`：`key`、相对 path、status、文件内容 SHA-256；
另保存该数组规范 JSON 的汇总 SHA-256。resume、merge 和 finalize 都重读 item 并重算，任何
item/index/tool version 漂移都 fail closed。

## 原子写

统一 helper：

1. 同目录创建唯一临时文件；
2. 写 UTF-8 bytes；
3. flush + `os.fsync`；
4. `os.replace` 到正式路径；
5. 尽力 `fsync` 父目录。

CSV、JSON、JSONL、README 与 progress 全部复用该 helper。残留临时文件不参与读取或合并。

## 阶段接口

### races

- 发现 URL 后按规范 URL 排序。
- 每页独立抓取并保存 `status=success|skipped|retryable_error|permanent_error`。
- `success` 保存页面稳定内部行序的前五个有效完赛者，并保留页面展示的官方名次。
- 完整性要求为五个唯一结果行/马匹；合法同着如 `1,2,2,4,5` 必须接受，重复同一马或
  非完赛行混入必须拒绝。
- 单页失败继续；阶段 index 汇总状态和错误，不依赖进程正常退出。

### profiles

- 从所有 race success item 构造行并排序。
- race 阶段按以下优先级形成不可变 lookup key：
  1. 页面提供稳定 horse identity/profile href：规范化为
     `region|source_host|normalized_source_identity`；
  2. 没有来源 identity：`region|normalized_display_name`。
- race URL、race name、date、grade 只进入有序 occurrence evidence，不进入 lookup key；
  因此无 profile URL 的同名马跨两场仍归并。若实际来源 identity 不同则保持分离。缺少足够
  身份证据的 fallback seed 带 `identity_confidence=insufficient`，最多进入 ambiguous，
  不得 exact。
- profile shard 只按 lookup key 取数，不在 shard 内改变身份 key。
- `merge_profiles` 汇总全部 shard：唯一 profile URL 是首选 canonical identity；多个
  lookup key 指向同一 URL 时确定性合并 names/regions/race contexts。URL 冲突、同一 lookup
  指向多个 profile 或字段身份冲突时生成独立 ambiguous canonical seed，不猜测收敛。
- 无唯一 URL 的 fallback `canonical_horse_key` 使用 lookup key；不会加入普通赛事上下文。
- 同名证据冲突保留为 ambiguous seed，不猜测合并。
- profile shard 按 lookup key；只有 merged profiles 冻结后，search/scoring shard 才按
  canonical key。规则均为 `int(sha256(key), 16) % shard_count`。

### wikidata_search

- query 生成顺序、语言和候选 QID 固定排序。
- 每匹马独立保存候选和每次搜索状态。
- 四类匹配状态要求该马全部计划 search 请求成功。全部成功且零候选才是 `no_page`；
  “部分成功为空 + 部分失败”和“已有候选 + 另一查询失败”都保持
  `resolution_state=error`，不评分，待重试补齐。
- 每次 search 请求保存 query/language/status/error_code；profile transport failure 同样沿
  canonical seed 传播，不得被后续搜索覆盖。

### wikidata_entities

- 汇总 candidate QID，固定排序后分批抓取。
- entity shard ownership 只按 QID 的稳定 SHA 分配；每批响应拆成逐 QID 原子实体 cache，
  每个 QID 都保存 success/not_found/retryable_error。
- `merge_entities` 先合并所有 QID cache。随后 scoring shard ownership 只按
  `canonical_horse_key` 分配，每匹马从 merged cache 读取自己完整的候选 QID 集；
  同一 QID 可被任意数量马匹引用但只保存一次。
- 评分前对 names、descriptions、aliases 和 evidence 排序。
- 任一候选实体不是成功终态会形成 `resolution_state=error`；错误码进入最终结果，
  `wikipedia_match_status` 留空。确定的零候选才是 `no_page`。

### finalize

- 只接受所有要求 shard 的完成 index。
- 校验上游 SHA、key 全覆盖、重复内容与冲突。
- 复用现有 `assign_horse_results` 与输出字段，但改为原子输出。
- 通过依赖注入/禁止 client 构造的测试证明无网络访问。
- review queue 包含 probable、ambiguous、no_page 和 resolution error。
- summary 断言四类状态加 resolution_error 等于 unique horse seeds。

## 确定性与时间证据

- 同一冻结 checkpoint tree 重复执行 merge/finalize 必须逐字节一致。
- 独立采集 run 的 `created_at/fetched_at/updated_at` 可不同；resume 保留已完成 item 的原时间，
  不重写。
- 自动化 fixture 注入固定 clock 验证中断/续跑与不中断字节一致；真实 clock 测试只比较规范化
  业务内容，并验证旧时间证据未改变。

## 网络主机门禁

UmaFans 与 Wikidata 使用独立 allowlist。HTTP client 禁止 requests 自动 redirect，每一跳：

1. 在发请求前校验 scheme 只能为 HTTP(S)、精确 host、允许端口且无 userinfo；
2. 收到 3xx 后解析 `Location`，在下一跳请求前重复校验；
3. 最多允许固定跳数，越界或非 allowlist 立即失败且不发送下一请求。

sitemap shard、race/profile href、Wikidata API/redirect 全部走相同的请求前校验。测试记录 fake
transport 收到的 URL，证明外链、私网、协议和端口越界时零越界请求。

## 时间预算和进度

`StageRunner` 在开始下一个 item/batch 前检查 monotonic elapsed 与预算；预算耗尽时先保存 index
和 progress，再以专用安全停止退出码结束。正常错误与安全停止区分。

进度计算只基于冻结输入总数。日志用 `print(..., flush=True)` 或 flush handler，示例：

```text
[stage=wikidata_search] 200/489 success=190 errors=10 cached=143 elapsed=00:41:10 eta=01:00:30
CHECKPOINT_SAVED path=...
```

## GitHub Actions

使用多 job DAG：

```text
tests -> races
      -> profiles(matrix) -> merge_profiles
      -> wikidata_search(matrix) -> merge_search
      -> wikidata_entities(matrix) -> merge_entities
      -> score_horses(matrix) -> merge_scores
      -> finalize
```

- matrix 固定 `strategy.fail-fast: false`。
- 各网络 job 60—90 分钟，脚本预算比 job timeout 少至少 10 分钟；预算耗尽使用专用安全停止
  退出码。真实 stage 不吞掉退出码 `75`：job 保持 failure、`needs` 下游不运行；upload step
  仍以 `if: always()` 执行并保留可恢复 checkpoint。后续精确恢复返回 `0` 后 DAG 才继续。
- progress/index 放在 stage+shard 专属目录，禁止多个 shard 覆盖根级 progress。
- artifact 名绑定 `${run_id}-${run_attempt}-${stage}-${shard}`，v4 不覆盖同名 artifact。
- workflow 禁止 attempt 通配下载和 `merge-multiple`。当前 DAG 只下载当前精确
  `${run_id}-${run_attempt}` artifact；跨 run 恢复必须同时提供唯一 `source_run_id` 与
  `source_attempt`，只下载该 attempt 的精确 artifact 名。下载后仍由 manifest/tool/input/
  upstream SHA 校验，不兼容即拒绝。结束时 `if: always()` 上传新 artifact。
- merge/finalize 下载所有上游 artifact，冲突 fail closed。
- `merge_entities` 只消费全部 entity shard completion index 并产出完整 entity index；
  `score_horses` 同时消费 merged search 和 merged entity index；`merge_scores` 要求全部
  horse shard 完成。`finalize` 只消费 merged races/profiles/scores completion index，
  不得直接消费不完整 shard。
- workflow 不再运行时改 tracked Python 源码。
- workflow 的第一轮只使用小样本/fixture smoke 验证 artifact 链；静态和集成测试覆盖一个
  shard 安全停止后由第二 attempt 恢复，而其他成功 shard 复用 artifact、不重跑。完整网络运行在小样本和
  reviewer 通过后单独触发，避免 PR 每次提交自动重跑数小时。

## 兼容与迁移

现有单体 CLI 不承诺向后兼容；PR #24 尚未合并、没有生产消费者。保留相同脚本入口和最终文件
格式，README 更新为阶段命令。旧 `search_cache` 不自动信任，除非转换后绑定本次 manifest。

## 安全边界

- 只允许 `umafans.run`/`www.umafans.run` 的 HTTP(S) 公开页作为 UmaFans 输入；
  redirect 后再次校验 host。
- Wikidata/Wikipedia 使用固定 host、明确 User-Agent、有界 timeout/retry/rate。
- 本地测试禁止真实网络。
- 生产服务器核验不是实现依赖，本轮不登录生产。
