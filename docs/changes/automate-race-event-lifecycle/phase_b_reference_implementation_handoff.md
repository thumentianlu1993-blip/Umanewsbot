# `automate-race-event-lifecycle` 阶段 B0.1 赛后内部参考源实现交接

## 0. 当前门禁

- 本交接最初基于 `origin/main@a59956b327157d29630fab1f1c98ba9c9cacfed0` 编写；实际实现
  worktree 的 `HEAD` 与 `origin/main` 已在开始阶段重新核对，精确值以当前 Git 运行态为准。
- 用户已明确授权实现阶段 B0.1；测试先行、子代理实现和主线程本地验证已完成。
- 独立方案 reviewer 第三轮结论为 `APPROVED`。独立代码 reviewer session
  `019fa021-3552-7f23-a17f-2cae48ccc4bb` 首轮对 fingerprint
  `f2463878ffa4011aa91cf5b3cd7c5fe817b66157691e9eaf6e309640623695cd`
  返回 `REVISE`，无 P0/P1、4 项 P2；四项均已按新增真实 RED 修复。
- 同一 reviewer 第二轮 inner session `019fa02f-1976-7d10-b177-a18a0216591e` 对
  fingerprint `561cdbf66dd3a26c702366bd113d2aed197dc98446eec34856d2c2c1350e9200`
  仍返回 `REVISE`，4 项直接 P2 均已先补真实 RED 后修复。
- 第三轮 inner session `019fa044-4483-72e1-b836-53e6900df34c` 对 fingerprint
  `22675d91cb097737bb678bd547874cce1ae1d7c481f416710911740a24981f06`
  关闭上一轮 4 项 P2，但新增 1 项 P1 与 3 项 P2，仍为 `REVISE`。这些 finding 已按新增
  真实 RED 修复。
- 第四轮 inner session `019fa051-bcf9-7e71-bd04-f11090fe8112` 对 fingerprint
  `a3f862fd93041831250fe855e383ee911843f6eb940433604c5a08b1f835b63b`
  关闭其中 3 项、部分关闭 Sporting Life description，仍有 2 项 P2 并返回 `REVISE`。
  两项已按新增真实 RED 修复。
- 第五轮 inner session `019fa062-e917-76e2-aacd-e807fb0f1f9b` 对 fingerprint
  `50b50866f19853534daad66c9a2cd18650d4d74cafbfebec106b09c8b36c274d`
  关闭第四轮 2 项 P2，但新增 4 项 P2，仍为 `REVISE`。四项已按新增真实 RED 修复；该轮
  修复后进入同一 reviewer 第六轮限定复审。
- 第六轮 inner session `019fa071-ca82-7b80-9af1-d4725efb6c` 对 fingerprint
  `41307729d9896c7fbd721b2e8864177990a7d190d3c25011b53a0bf284db0d87`
  关闭第五轮 4 项 P2，但新增 5 项 P2，仍为 `REVISE`。五项已按新增真实 RED 修复；该轮
  修复后进入同一 reviewer 第七轮限定复审。
- 第七轮 inner session `019fa07f-90e2-7f60-b08d-125e01d55ba3` 对 fingerprint
  `6dd68951fe0ff90847c74f3873fb0539eec8226441473c294e7c444591ebba1a`
  关闭第六轮 5 项 P2，但新增 3 项 P2，仍为 `REVISE`。三项已按新增真实 RED 修复；该轮
  修复后进入同一 reviewer 第八轮限定复审。
- 第八轮 review session `019fa08e-e782-7d31-9cbc-921bb3b4efbd`、fingerprint 前缀
  `d98034f…` 发现唯一 P2：runtime safe HTTP 会被默认开发 bind mount 遮蔽。3 项真实 RED
  后已修复为 stable 唯一实现、runtime 兼容 wrapper、collect 直接 import stable。该轮
  修复后进入同一 reviewer 第九轮限定复审。
- 第九轮 session `019fa09e-88c5-7180-a678-39874ff6e045` 对 fingerprint
  `84e8f4fafc4db634911c9aa18f6f473bdba12078e2957072a660434505c5ce6f`
  返回 `REVISE`，含 1 项 P1 与 3 项 P2；四项均已按真实 RED 修复，随后进入第十轮。
- 第十轮 session `019fa0ad-c024-7a21-8ebb-31b19df760ab` 对 fingerprint
  `abbc00318318447abb86627ffe29a076012f8eceee4aa1b8d3f6c0c157dc4b20`
  返回 `REVISE`，唯一 P2 是 observations 与 ledger `outcome=parsed` event 必须精确一一
  对应，`parse_error` event 必须零 observation。2 项真实 RED 后已最小修复；既有正向
  fixture 已改为合法 `parsed + observation`，replay 继续验证；该轮修复后进入第十一轮。
- 第十一轮 session `019fa0b9-b2c8-77d0-9473-7caff58d87eb` 对 fingerprint
  `ef778594f1d471a239432c6bd65054dcb2491fb918c46a660ea321436a827b0d`
  返回 `REVISE`，2 项 P2 是共享 safe HTTP 默认 `4MiB / 2 跳` 破坏 legacy 大
  PDF/redirect，以及跨日 run 的单日报告错误误归。纯 `origin/main` 调查确认旧 transport
  无 body cap 且 `urllib` 默认处理 redirect；3 项真实 RED 后，legacy 默认不自定义这些
  限制，collect 显式保留 `4MiB / 2 跳`，report 按 event/date 归属并单列
  `unattributed_errors`；该轮修复后进入第十二轮。
- 第十二轮 session `019fa0c7-7f55-7960-9f5d-5b81ba13437c` 对 fingerprint
  `6b0246db6647786e351492822d86f70a8dd15dbb272a19a6a34a324f15ca7b3b`
  返回 `REVISE`，2 项 P2 是 matched 未核对来源赛事名，以及单日无 receipt 错误未回退
  run 唯一日期。反例 RED 后新增公开 normalization helper，manifest 冻结
  `normalized_accepted_race_names` 并纳入 snapshot SHA，record 要求 exact membership；
  single-day fallback 与过时 fixture 已修正。当前 B0.1 `89/89`、race-live `23/23`、
  历史 HTTP/parser `82/82`（4 skip），真实 PostgreSQL 并发/锁 `2/2`、`SET_NULL`
  `1/1`，临时容器已删除；该轮修复后进入第十三轮。
- 第十三轮 session `019fa0db-0a80-72c0-a6ad-bb1142432a83` 对 fingerprint
  `384ef97820f9e6d9c0c8f6df7190f1fb546746570aff018379b742a41e3b0c00`
  返回 `REVISE`，3 项 P2 是 collect 异名未降 `source_only`、多日错误 detail 缺
  `local_date`、`--event-id` 漏无 receipt 匹配错误 run。3 项真实 RED 后，collect 按
  exact frozen name 分类，ledger 逐 event 冻结日期并由 record 核验，event filter 按错误
  detail 纳入 run 且隔离其他错误；6 个旧 fixture 已补必需字段。当前 B0.1 `93/93`、
  race-live `23/23`、历史 HTTP/parser `82/82`（4 skip）、真实 PostgreSQL `3/3` 且临时
  容器已删除；该轮修复后进入第十四轮。
- 第十四轮 session `019fa0ea-65a3-7383-b208-c0f571e7b98a` 对 fingerprint
  `18ac8b531f2d123b132fbe45104999feeea814315087ac6e4cdc0d043a4baeae`
  返回 `REVISE`，2 项 P2 是 record 丢 artifact 采集窗口，以及无 receipt 失败 run 未计
  `duplicate_runs`。测试锁定最早 ledger `fetched_at` 至 artifact `completed_at`，拒绝
  逆序/naive/显著未来，并覆盖同 event/day 重复失败 run；修复增加 5 分钟 clock skew、
  原子保存签名窗口，并统一 receipt/error-detail run membership。当前 B0.1 `96/96`、
  race-live `23/23`、历史 HTTP/parser `82/82`（4 skip）、真实 PostgreSQL `3/3` 且临时
  容器已删除；该轮修复后进入第十五轮。
- 第十五轮 session `019fa0fa-b908-7d43-9f7e-807bf132a9a3` 对 fingerprint
  `59ffcb96972cef74dcff8df87e5a9d1b0f3923ecf59f5f5b594e58e48594424f`
  返回 `REVISE`，2 项 P2 是只校验最早 ledger 时间，以及 observation provenance 的
  `fetched_at/final_url` 未逐 event 绑定。重签 artifact 反例 RED 后，record 要求
  `max(ledger fetched_at) <= artifact.completed_at`，且 observation 的 URL、时间及
  raw/ref/hash 与 manifest、parse ledger、response 逐 event 精确一致。当前 B0.1
  `98/98`、race-live `23/23`、历史 HTTP/parser `82/82`（4 skip）、真实 PostgreSQL
  `3/3` 且临时容器已删除；该轮修复后进入第十六轮。
- 第十六轮 session `019fa106-3b52-7a02-b756-31f718ffe4d0` 对 fingerprint
  `571664940ea3e77b60368fe4ddf72292404060fedfb27f281d6b7f7d1f815cc7`
  返回 `REVISE`，唯一 P2 是 Payload/Receipt `QuerySet.update/bulk_update/delete`
  可绕过 append-only。6 项真实 RED 和 5 项实例/`SET_NULL` 正例后，专用
  QuerySet/Manager 拒绝 Payload 全部批量变更；Receipt 仅允许 Collector 精确执行
  `event=None/event_id=None`，其他均拒绝；无需迁移。当前 B0.1 `104/104`、race-live
  `23/23`、历史 HTTP/parser `82/82`（4 skip）、真实 PostgreSQL `3/3` 且临时容器已删除；
  Compose 仍未验证。下一门禁是同一 reviewer 最终限定复审，review 与 release 均未完成。
- 第十七轮 session `019fa113-9c02-7c63-b48d-466c40d323cf` 对 fingerprint
  `5095a06e326a9cef470f4ef5d2111c87e8daa77a45fbc9507a27b024369edea7`
  给出 `APPROVED`，P0/P1/P2/P3 均为 0。
- 发布前 fetch 发现 `origin/main` 前进到 `6ac08e40`，候选已通过可恢复 stash 迁移到最新
  main；Sporting Life/ZEturf 同时保留上游 recovery 能力和 stable parser 委托。集成后
  B0.1 `104/104`、race-live `23/23`、历史 HTTP/parser `82/82`（4 skip）、真实
  PostgreSQL `3/3` 通过。上游新增组合的 `14/87` macOS 路径错误在纯最新 main 精确复现。
- 该 latest-main 集成版本尚未复审、commit、push 或创建 PR；必须重新冻结 fingerprint，
  复用同一 reviewer 审核后再取得当前版本发布授权。
- 禁止使用 OpenSpec skills、OpenSpec CLI 或新建 OpenSpec change。
- commit、push、PR、部署、联网、生产迁移和生产写入仍分别需要后续明确授权。

## 1. 当前真实状态

### 1.1 阶段 A

- PR `#25` 的阶段 A schema/code 已在生产以
  `RACE_EVENT_LIFECYCLE_ENABLED=false`、`RACE_EVENT_LIFECYCLE_MODE=off` 部署；
- migration `0058/0059` 已应用；
- 生命周期四表仍为零记录，未启用 shadow/enforce；
- 生产 35 场只读 dry-run 为 `7 transition / 28 noop / 0 error`，全部没有
  `race_datetime`；
- 阶段 A 的时间状态推进不依赖任何 provider，阶段 B0.1 不应改变该合同。

详细证据见 `production_release_20260726.md`。开始实现前重新核对生产状态，不把文档当作当前
服务器证明。

### 1.2 可复用代码

- Sporting Life：
  `runtime/tools/prepare_uk_sportinglife_race_detail_candidates.py`
- ZEturf：
  `runtime/tools/prepare_france_zeturf_race_detail_candidates.py`
- HRN：
  `runtime/tools/prepare_us_hrn_race_detail_candidates.py`
- 请求安全与 cache：
  `runtime/tools/race_event_safe_http.py`、
  `runtime/tools/race_event_request_budget.py`、
  `runtime/tools/race_event_source_cache.py`
- 现有 adapter/run 编排：
  `server/stable/services/race_event_crawl_orchestration.py`、
  `server/stable/services/historical_batch_pipeline.py`

parser 已能输出历史 `runners/results` 候选，但现有
`import_race_event_detail_candidates --apply` 会更新正式表，阶段 B0.1 禁止调用。

## 2. 实现目标

在不改变公开赛事和赛果的前提下，让站长可在后台查看 Sporting Life、ZEturf、HRN 的低频
结构化观察、匹配证据、内容变化与错误。

首个实现单元 B0.1 只包含：

1. 内部 collection run、不可变 payload 和逐 run receipt 持久模型；
2. 从三个现有赛后 parser 抽取并由历史 CLI 共用的 parse-only adapter/reference wrapper；
3. 离线 fixture、manifest-bound collect、离线 record 和 report 命令；
4. 只读 Django Admin；
5. 运行统计和 7 个逐日 one-shot 的多日观察报告。

不包含：

- 修改 `RaceEvent`、runner/result、field authority 或 lifecycle 状态；
- 创建 `RaceEventDataCandidate`；
- 创建 race-live observation/revision/projection；
- 公开页面、公开 API、新闻或 QQ 输出；
- 人工 promotion；
- 赛前 racecard route；
- Celery Beat、task、queue 或无人值守 selector；
- TRA、JRA、NAR、HKJC 官方同步实现；
- 启用生产调度或执行联网 proof。

## 3. 数据模型

### 3.1 `RaceReferenceCollectionRun`

建议字段：

- `source_key/country_region/parser_version`
- `scope_manifest_sha256`
- `local_date_from/local_date_to/target_count`
- `status`
- `trigger_kind/trigger_task_id`
- `started_at/finished_at`
- `request_count/cache_hit_count`
- `matched_count/unmatched_count/ambiguous_count/partial_count`
- `unchanged_count/changed_count/error_count`
- `artifact_sha256`
- `summary/error_summary`

约束：

- source/region 必须命中固定 registry；
- unique `(scope_manifest_sha256,artifact_sha256)`；
- digest 必须是 64 位 SHA-256；
- count 非负；
- finished 状态必须有 `finished_at`；
- 模型只记录内部运行事实，不带 publish/apply 状态。

### 3.2 `RaceReferencePayload`

建议字段：

- `source_key/provider_event_key`
- `observation_key/payload_sha256`
- `structured_payload`
- `created_at`

约束与索引：

- unique `(source_key, observation_key, payload_sha256)`；
- structured payload 只允许版本化、大小有界的 JSON；
- payload append-only；同内容只保存一次。

### 3.3 `RaceReferenceReceipt`

建议字段：

- `run/payload`
- `source_url/final_url/source_observed_at/fetched_at`
- `parser_name/parser_version/legacy_payload_sha256`
- `raw_sha256/source_cache_ref/provenance_sha256`
- nullable `event`
- `match_status/match_confidence/match_evidence`
- `event_snapshot_sha256/classification_version`
- `is_partial/gap_codes/recorded_at`

约束与索引：

- unique `(run,payload)`；
- index `(event, recorded_at)`；按来源筛选通过 immutable payload join；
- source cache 只允许 artifact 内安全相对标识，不接受任意绝对路径；
- `matched` 必须有 event；其他状态不绑定 event；
- `run/payload` 使用 `PROTECT`，event 使用 `SET_NULL`；
- receipt append-only，不因后续重新匹配改写历史。

record 命令以 `(manifest_sha256,artifact_sha256)` 取得 PostgreSQL transaction advisory lock，
在同一事务内创建/复用 run、payload、receipt；并发唯一约束竞争重读为 replay。

## 4. 服务边界

建议新增：

```text
server/stable/services/race_reference_sources.py
```

公开接口建议：

```python
normalize_reference_payload(...)
match_reference_observation(...)
record_reference_collection(...)
build_reference_collection_summary(...)
```

要求：

- 新增 `runtime/tools/race_reference_parsers/` 包，按来源暴露
  `parse_reference_page(raw_bytes, source_url, parser_context)`；函数不得联网、读数据库或写文件；
- 把现有三个历史 CLI 的解析实现抽到上述模块，并让原 CLI 反向调用相同函数，避免维护两套
  DOM parser；现有历史 candidate JSONL/summary 合同和回归必须保持不变；
- collect 只请求 manifest 中逐场冻结的精确 `source_url`，不得调用历史 CLI 的日期发现、
  ZEturf R/C 扫描、HRN/赛事名“取首个候选”等路径；
- 不使用 shell/subprocess 运行任意脚本；parse-only 输出仍须经过 reference schema validator；
- 解析/规范化/匹配是纯函数，可用冻结 HTML/JSON fixture 测试；
- record 在单事务中写 run/payloads/receipts，失败整批回滚；
- 完全相同重放复用 payload，但新 run 追加 receipt；
- 变化内容追加新 payload；相同 payload 重新分类追加 receipt；
- 不能 import 或调用 `apply_data_candidate`、race-live projection 或 publish/QQ service；
- event identity 最少核对 region、local date、racecourse 和 provider-specific race identity；
- 名称单信号只能 ambiguous/unmatched。

### 4.1 reference schema

精确 `race_reference_observation_v1`、legacy 降权映射、forbidden keys、canonical JSON、SHA、
长度/item/depth/大小及 completeness 规则以 `internal_reference_sources.md` 4.4 为唯一合同。

特别要求：

- parser 的 `official_finish_position` 映射为 `source_reported_finish_position`；
- `is_confirmed` 丢弃；
- `official/is_confirmed/authority/publication/apply` 相关 key 递归禁止；
- payload canonical bytes 最大 256 KiB，runner 最大 80，无 float；
- HRN payout/also-rans 默认 partial。
- payload hash 只覆盖 semantic facts；URL、抓取时间、raw/cache、parser/legacy hash 进入逐
  receipt provenance hash，因此事实不变的每日抓取复用 payload。

### 4.2 manifest

manifest 只接受 `purpose=internal_reference_post_race`、固定 source/region 和 finished event。
精确 schema、source key、canonical hash、event snapshot、URL host/path、artifact file
manifest/COMPLETE 合同见
`internal_reference_sources.md` 第 5 节。

source-specific strong identity 必须同时满足 provider key 与 URL 语法：Sporting Life 数字 race
ID、ZEturf `date+R/C`、HRN `track+date+race_no`。parser context 只从 key 派生；HRN 页面必须按
race number 唯一命中，禁止名称 fallback 或取第一个候选。

record 必须同时核对：

- manifest 文件及用户提供 SHA；
- artifact 文件及用户提供 SHA；
- artifact 内 manifest SHA、parser/reference schema version、逐 response raw hash 和
  `COMPLETE` marker；
- 当前 DB event snapshot；
- source/region/host/path。

任一失败整批零写。

## 5. 命令与任务

建议新增管理命令：

```text
build_internal_race_reference_manifest
collect_internal_race_references
record_internal_race_references
report_internal_race_reference_observation
```

精确参数合同：

```text
build_internal_race_reference_manifest
  --source-key <fixed-enum>
  --targets-file <strict-json>
  --output <new-file>

collect_internal_race_references
  --manifest-file <path>
  --manifest-sha256 <64hex>
  --output-dir <new-empty-dir>
  [--allow-network]
  [--max-requests 1..100]

record_internal_race_references
  --manifest-file <path>
  --manifest-sha256 <64hex>
  --artifact-dir <path>
  --artifact-sha256 <64hex>

report_internal_race_reference_observation
  --source-key <fixed-enum>
  --date-from <YYYY-MM-DD>
  --date-to <YYYY-MM-DD>
  [--event-id <positive-int>]
  --output <new-file>
```

`build` 永远只读数据库。`targets-file` 只允许 `event_id/provider_event_key/source_url` 三字段，
1..100 项，无重复；命令补齐 DB snapshot、parser/schema version 与 `generated_at`，输出 canonical
manifest 和 SHA，不联网、不写数据库。生成结果必须人工核对，并在联网或 record 授权中明确
引用该 manifest SHA；“命令成功生成”本身不代表已批准。

`collect` 默认：

- 无 `--allow-network` 时只读已有 cache/fixture；
- 永远只输出 artifact，数据库零写；
- 必须提供冻结 `--manifest-file` 与 `--manifest-sha256`；
- source/event/date/request limit 必填或有安全上限；
- 禁止 auto-discover；
- 每个 event 只请求 manifest 精确 URL；`--max-requests<=100` 且不超过 event 数；
- timeout 固定 15 秒，不自动重试；连续 3 个 403/429/timeout/5xx 后终止本来源；
- 输出目录必须不存在或为空，成功后最后写 `COMPLETE`；
- 输出 source、target、request、matched/ambiguous/partial/error 计数。

`record`：

- 强制无网络；
- 必须提供 manifest/artifact 文件和两个 SHA；
- DB drift、registry、schema、host/path、hash/marker 全部重验；
- advisory lock + atomic 写三层模型；
- 同 manifest/artifact 并发重放返回 replay。

阶段 B0.1 不修改 `server/stable/tasks.py`、Celery route、Beat、Compose worker 或启动脚本。
多日观察为每天逐来源显式运行 one-shot collect/record；自动调度属于 B0.2。

### 5.1 HTTP

现有 `race_event_safe_http.fetch_https()` 必须测试先行增加：

- `Content-Type` 仅允许 `text/html`、`application/xhtml+xml` 及 charset 参数，缺失/冲突拒绝；
- `Content-Length` 与流式实际读取双重 4 MiB 上限；
- 最多 2 次 redirect，每跳重验 HTTPS/host/path；
- 超限/类型/redirect/timeout 只失败当前来源。

raw cache、请求账本、budget、manifest 与 COMPLETE 都保存在本次输出目录；record 不读取容器
临时目录或未绑定 cache。

## 6. Admin

新增三个只读 admin：

- collection run 列表、来源/地区/时间/计数/错误；
- payload 列表、来源事实、hash、completeness；
- receipt 列表、赛事、匹配状态、差异、partial/gap、来源链接。

权限与显示：

- 专门 `view_racereference*` 权限；
- add/change/delete 全部 false；
- 不提供 promotion/action；
- 页面固定显示“仅内部参考，不影响公开赛事或正式赛果”；
- 禁止把 legacy `is_confirmed/official_finish_position` 渲染为正式标签；
- structured payload 以大小有界、转义后的只读视图展示；
- artifact 下载若纳入首轮，必须额外权限和 `OperationLog`；否则首轮不实现下载。

## 7. 测试先行

实现授权后先由测试 subagent负责以下文件：

- 新建 `server/stable/test_race_reference_sources.py`
- 新建 `server/stable/test_race_reference_sources_postgres.py`
- 扩展 `server/stable/test_historical_race_detail_direct_urls.py`
- 扩展 public race/admin 与“未新增 task/queue”相关测试

必须取得真实 RED，至少覆盖：

1. 新模型和 record service 尚不存在；
2. 三个 wrapper 尚不能产生统一 v1 schema；
3. public isolation 尚无结构性保证；
4. 当前尚无 B0.1 管理命令，且实现后必须继续证明没有新增 Celery task/route/Beat/worker；
5. 管理命令尚不能做 manifest 绑定的零写 collect/离线 record。

详细矩阵见 `test_cases.md` B32–B57。RED 不得来自缺 fixture、迁移依赖、语法或网络。

## 8. 实现 subagent 文件边界

取得实现授权后，建议串行：

1. 测试 subagent：只拥有新测试和必要 fixture；
2. application subagent：
   `models.py`、migration、reference service、admin；
3. integration subagent：
   三 parser 受限 adapter、collect/record/report 命令、safe HTTP；
4. operations/documentation subagent：
   只补运行手册和实际验证证据。

所有 subagent 均不得 commit、push、PR、联网、部署或写生产，且不得回退其他 worktree/线程改动。

## 9. 主线程验证

- 新聚焦测试；
- 三 parser 全部既有回归；
- public race calendar/detail 及 cache/query-count 回归；
- lifecycle 56 项及 race-live 回归；
- 新闻发布/QQ 零触发回归；
- 断言未新增 Celery task/route/Beat/worker；
- PostgreSQL advisory lock、事务、跨 run/并发重放和重新匹配；
- Django check；
- `makemigrations --check --dry-run`；
- Compose config；
- `git diff --check`。

联网、多日观察和生产 record 不属于本地 GREEN。

## 10. review 与发布

1. 主线程验证通过后冻结 uncommitted fingerprint；
2. 使用未参与实现的独立 reviewer 执行 Codex 原生只读 review；
3. 有 finding 时由实现 subagent 修复，复用同一 reviewer 会话复审；
4. review 成功后停止，等待用户对当前 fingerprint 的 commit/push/PR 授权；
5. 代码发布、只读联网 proof、内部 record 写入、连续观察启用分别取得授权；
6. 第一轮生产只部署 schema/code；阶段 B0.1 没有调度入口；
7. 之后依次：离线 fixture -> one-shot 网络 dry-run -> 小范围 internal record ->
   7 个逐日 one-shot 连续观察；
8. 任一阶段都不存在公开发布步骤。

## 11. 完成定义

阶段 B0.1 代码完成必须同时满足：

- 三源统一内部观察合同；
- 内部数据在 admin 可审计；
- public/news/QQ/race-live/lifecycle 零耦合；
- payload/receipt 分层、重放、变化、重新匹配、歧义、partial、来源失败均有测试；
- manifest 是信任根，legacy official 语义已降权；
- 无 Celery/Beat；one-shot request budget、HTTP MIME/size/path 和无自引用 artifact 门禁；
- 独立 review 通过；
- 尚未联网、部署或写生产时如实保持相应状态。
