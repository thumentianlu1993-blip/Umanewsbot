# Sporting Life、ZEturf、HRN 内部参考源合同

## 1. 状态与决策

- 决策日期：`2026-07-27`。
- 用户已确认 Sporting Life、ZEturf、Horse Racing Nation（HRN）可由本站保留现有解析器并
  低频使用。
- 三个来源的新增生命周期采集结果仅供站长在内部后台参考，不进入公开赛事、新闻、QQ、搜索、
  sitemap、公开 API 或任何第三方输出。
- 本文记录产品与工程边界，不替代来源方授权原件，也不改变既有历史赛事导入事实。
- 当前只完成设计；未授权修改测试、应用代码、迁移、Celery、生产配置或执行联网采集。

## 2. 来源角色

| 来源 | 地区 | 已有解析器 | 内部参考用途 | 明确禁止 |
|---|---|---|---|---|
| Sporting Life | 英国 | `runtime/tools/prepare_uk_sportinglife_race_detail_candidates.py` | 已完赛页面中的实际出走、jockey、trainer、draw、退赛/异常完赛和来源所报结果交叉核验 | 不把赛后页面称为赛前 racecard；不直接更新公开赛事；不产生 official |
| ZEturf | 法国 | `runtime/tools/prepare_france_zeturf_race_detail_candidates.py` | 已完赛页面中的实际出走、draw、jockey、trainer、负磅、退赛、到达顺序和赔率交叉核验 | 不把赛后实际出走称为赛前声明；不覆盖 France Galop；不产生 official |
| Horse Racing Nation | 美国 | `runtime/tools/prepare_us_hrn_race_detail_candidates.py` | 已完赛 track-day/race 的实际出走、jockey、trainer、赔率及部分来源所报结果交叉核验 | 不把赛后页面称为赛前 racecard；不以 payout/also-rans 重建结果冒充完整正式赛果 |

三个来源统一登记为：

```text
source_role = internal_reference
publication_capability = none
result_authority = none
field_apply_capability = none
```

“解析成功”“匹配成功”“内部可见”“允许写公开字段”是四个不同概念。前三者全部成立也不能推出
第四项。

## 3. 与既有能力的关系

现有三个 parser 已用于历史详情候选和受控导入，能够输出 `runners/results` JSONL；现有
`import_race_event_detail_candidates --apply` 会把候选写入正式赛事表。因此生命周期内部参考
链不得直接复用该 apply 入口。

阶段 B0.1 应：

1. 从 parser 中抽取正式、可导入的 parse-only 函数，并让历史 CLI 反向复用同一函数；
2. 用新 wrapper 把 parser 输出规范化为 `race_reference_observation_v1`；
3. 只处理 `status=finished` 的赛后参考结果；不宣称三个现有 parser 已支持赛前 racecard；
4. 写入独立、只读后台模型，不创建 `RaceEventDataCandidate`；
5. 不调用 `save_data_candidate()`、`apply_data_candidate()`、race-live revision/projection；
6. 不改变既有历史 importer 的行为；历史数据是否公开仍由其原有审核、SHA、apply 和页面门禁决定。

本决策不追溯删除或隐藏已按历史赛事流程正式导入的数据；它只约束新增的生命周期参考采集路径。
Sporting Life/HRN 的赛前入口与 ZEturf 赛前字段若以后需要，必须使用新 fixture/proof 另行设计，
不能把赛后 parser 的存在写成赛前已覆盖。

## 4. 内部观察数据合同

### 4.1 `RaceReferenceCollectionRun`

每次来源运行至少记录：

- `source_key`、`country_region`、`parser_version`；
- 冻结 event manifest SHA-256、日期范围和目标数；
- `started_at/finished_at/status`；
- 请求数、cache hit、HTTP/parse/match 错误；
- matched/unmatched/ambiguous/partial/unchanged/changed 数；
- 输出 artifact SHA-256；
- 触发方式和任务 ID；
- 最近错误的结构化 code，不保存凭据或整页正文。

`(scope_manifest_sha256,artifact_sha256)` 唯一；相同输入重放返回既有 run。run 不表示调度
control，也没有 next-run/claim 字段。

### 4.2 `RaceReferencePayload`

来源结构化事实不可变保存：

- `source_key/provider_event_key`；
- `observation_key` 与 `payload_sha256`；
- 完整 `race_reference_observation_v1`；
- `created_at`。

唯一键：

```text
(source_key, observation_key, payload_sha256)
```

完全相同来源内容只保存一个 payload；相同 observation key 内容变化时追加新 payload，不覆盖旧记录。

### 4.3 `RaceReferenceReceipt`

每个 collection run 对每个 payload 保存独立 receipt：

- `run/payload`；
- `source_url/source_observed_at/fetched_at/parser_name/parser_version`；
- `raw_sha256/source_cache_ref/provenance_sha256`；
- nullable `event_id`；
- `match_status/match_confidence/match_evidence`；
- manifest event snapshot/hash；
- `is_partial/gap_codes`；
- `classification_version`；
- `recorded_at`。

唯一键为 `(run,payload)`。完全相同 payload 在第二个 run 复用 payload、追加新 receipt，因此
两个 run 都有完整 membership；同一 payload 后续在新 manifest/分类版本下从 ambiguous 变为
matched 时只追加新 receipt，不修改旧 receipt。

并发 record 对 `(manifest_sha256,artifact_sha256)` 取得 PostgreSQL transaction advisory lock，
在事务内 `get_or_create` payload/run/receipt；唯一约束竞争必须重读为 replay，不能使整批回滚。

### 4.4 `race_reference_observation_v1`

规范化 payload 是“来源所报语义事实”，只允许以下精确顶层字段：

```text
schema_version: 1
source_key: reference_sporting_life|reference_zeturf|reference_horse_racing_nation
country_region: united_kingdom|france|united_states
provider_event_key: string(1..255)
race: {
  source_race_name:string<=255,
  source_racecourse:string<=255,
  local_date:YYYY-MM-DD,
  source_start_time:string<=64
}
runners: array<=80 of {
  source_runner_key:string<=255,
  horse_number:string<=32,
  draw:string<=32,
  horse_name:string<=255,
  jockey_name:string<=255,
  trainer_name:string<=255,
  carried_weight:string<=64,
  odds_value:string<=64,
  running_status:string<=64,
  source_reported_finish_position:string<=32,
  margin:string<=64
}
completeness: {
  race_identity:complete|partial|unknown,
  runners:complete|partial|unknown,
  results:complete|partial|unknown,
  gap_codes:array<=32 of unique string<=64
}
```

`observation_key` 固定为 `source_key + ":" + provider_event_key`。`payload_sha256` 只对上述
semantic payload 的 canonical bytes 计算，不包含抓取时间、URL、raw hash、cache path、parser
版本或 legacy payload hash，因此来源事实相同但每日抓取时间/raw HTML 包装不同仍复用 payload。

每个 receipt 另保存精确 provenance 对象：

```text
{
  source_url: HTTPS URL(1..1000),
  final_url: HTTPS URL(1..1000),
  source_observed_at: aware ISO-8601|null,
  fetched_at: aware ISO-8601,
  parser: {name:string<=64, version:string<=64},
  legacy_payload_sha256: sha256,
  raw_sha256: sha256,
  source_cache_ref: safe relative path(1..500)
}
```

`provenance_sha256` 对 provenance 对象应用同一 canonical JSON 算法。相同 semantic payload 的
不同抓取各有 receipt/provenance；`unchanged_count` 指本次 receipt 的 payload hash 与该
event/source 上一次 matched receipt 相同，不表示 raw/provenance 相同。

不允许额外字段；递归禁止
`official/is_official/is_confirmed/official_finish_position/result_confirmed_at/authority/
publication_status/apply`。legacy parser 的 `official_finish_position` 只能降级复制到
`source_reported_finish_position`，`is_confirmed` 仅用于 adapter 输入验证后丢弃，绝不能进入
reference payload 或 admin 标签。

HRN 使用 payout/also-rans 时 `results` 默认 `partial`；只有专门的新 proof 才能改变。
ZEturf 到达行少于非退赛 runner 或存在未解析名次时为 `partial`。Sporting Life 只有所有已声明
runner 都有明确完成/非完成状态时才可 `complete`；否则 `partial/unknown`。completeness 只表示
来源页面结构完整度，不表示官方权威。

规范化前只接受内置 JSON 类型、最大深度 12、禁止 float、所有字符串先做 Unicode NFC。
canonical bytes 固定为：

```python
json.dumps(
    normalized_payload,
    sort_keys=True,
    separators=(",", ":"),
    ensure_ascii=False,
    allow_nan=False,
).encode("utf-8")
```

canonical bytes 上限 `262144` bytes，`payload_sha256=SHA256(canonical_bytes)`。超深、超长、
超 item、额外/禁止字段或 hash 不一致均整条拒绝，不截断后继续。

### 4.5 匹配状态

- `matched`：唯一命中一个赛事且通过地区、当地日期、赛场及赛事身份合同；
- `unmatched`：没有安全候选；
- `ambiguous`：存在多个候选或关键身份冲突；
- `source_only`：来源页可解析，但当前不应绑定本地赛事。

仅赛事名称相似不得成为 `matched`。Sporting Life sponsor 名、ZEturf `R/C`、HRN track/race
编号必须保留在证据中；误匹配不会改变任何赛事字段。

## 5. Manifest 信任根

collect/record 均只接受 `schema_version=1`、`purpose=internal_reference_post_race` 的 manifest。
一个 manifest 只允许一个固定 `source_key`，精确 schema 为：

```text
schema_version: 1
purpose: internal_reference_post_race
source_key: 固定枚举
reference_schema_version: 1
parser: {name:string<=64, version:string<=64}
generated_at: aware ISO-8601
events: array(1..100) of {
  event_id: positive integer,
  slug: string(1..255),
  country_region: 固定枚举,
  local_date: YYYY-MM-DD,
  timezone_name: string(1..64),
  racecourse: string(1..255),
  original_name: string(1..255),
  status: finished,
  provider_event_key: string(1..255),
  source_url: HTTPS URL(1..1000),
  event_snapshot_sha256: sha256
}
```

不允许额外字段或重复 event/provider identity。`event_snapshot_sha256` 是以下精确对象应用同一
canonical JSON 算法后的 SHA-256：

```text
{
  event_id, slug, country_region, local_date, timezone_name,
  racecourse, original_name, status
}
```

整份 manifest SHA 不写入 manifest 自身，由调用者对 canonical manifest bytes 计算并通过
`--manifest-sha256` 提供。

source key 唯一冻结为：

- `reference_sporting_life -> united_kingdom`
- `reference_zeturf -> france`
- `reference_horse_racing_nation -> united_states`

`provider_event_key` 由来源 URL 中的强身份导出并逐字核对：

- Sporting Life：`sl:<race_id>`，`race_id` 为 URL
  `/racing/results/YYYY-MM-DD/<course>/<race_id>/<slug>` 中的正整数；
- ZEturf：`zt:<YYYY-MM-DD>:R<meeting>C<race>`，meeting/race 均为正整数，必须与 URL
  `/fr/course-du-jour/YYYY-MM-DD/R<meeting>C<race>-<slug>` 一致；
- HRN：`hrn:<track-slug>:<YYYY-MM-DD>:R<race>`，race 为正整数；track/date 必须与 URL
  `/entries-results/<track-slug>/YYYY-MM-DD` 一致。

`parser_context` 不接受调用者自由 JSON，而是仅由验证后的 provider key 派生。HRN parse-only
函数必须在 track-day 页中按 `race_no` 精确找到且只找到一场；0 或多场均为 parse error，禁止
回落到赛事名模糊匹配或 `candidates[0]`。Sporting Life/ZEturf 也必须回验页面中的强 ID 或
R/C；页面无法证明时保持失败，不用名称补足强身份。

固定路由：

| source key | host allowlist | path pattern |
|---|---|---|
| `reference_sporting_life` | `sportinglife.com` 及其子域 | `^/racing/results/` |
| `reference_zeturf` | `zeturf.fr` 及其子域 | `^/fr/course-du-jour/` |
| `reference_horse_racing_nation` | `horseracingnation.com` 及其子域 | `^/entries-results/` |

旧的 `sporting_life_result_detail/uk_sporting_life_detail` 等名称只能作为 adapter 输入 provenance，
不得进入 registry、模型或权限判断。

manifest 使用与 payload 相同的 strict JSON、NFC、无 float、sorted compact JSON 算法计算
SHA-256。record 前重新读取数据库并重算 event snapshot；event 不存在，或 region/date/timezone/
racecourse/name/status/slug 任一漂移即整批零写。`status` 必须为 `finished`。

source URL 必须命中固定 HTTPS host/path；redirect 每一跳及 final URL 也必须命中同一合同，
且不得改变 Sporting Life race ID、ZEturf date/R/C 或 HRN track/date 强身份。禁止凭任意
自签 SHA 扩大 host/path 或切换赛事。

collect 只按 manifest 中的精确 `source_url` 请求，不使用三个历史 CLI 的日期页发现、R/C 扫描、
“取首个候选”或名称模糊选择逻辑。parse-only 模块固定新增在
`runtime/tools/race_reference_parsers/`，每个来源公开 `parse_reference_page(raw_bytes,
source_url, parser_context)`；它不联网、不读数据库、不写文件。原有历史 CLI 改为调用同一
parse-only 函数，既有候选输出合同保持不变。collect 管理命令负责受限 HTTP、artifact 与严格
身份匹配，不通过 shell/subprocess 执行任意脚本。

collect 成功目录的允许集合精确为：

```text
raw/<event_id>.body
manifest.json
references.jsonl
request_ledger.jsonl
artifact.json
COMPLETE
```

`manifest.json` 必须与调用者提供 manifest 的 canonical bytes 逐字节一致。
`artifact.json.files` 只列 `raw/*.body`、`manifest.json`、`references.jsonl`、
`request_ledger.jsonl`，逐项绑定
安全相对路径、size 和 SHA-256；不列 `artifact.json` 自身，也不列 `COMPLETE`。它另绑定
manifest SHA、parser/reference schema version、逐 response raw SHA、JSONL/ledger SHA 和完成
时间。`artifact_sha256` 是 canonical `artifact.json` bytes 的 SHA-256；成功后最后原子写
`COMPLETE`，其内容只是一行该 SHA。进程锁位于输出目录外的同级 `<output-dir>.lock`，不属于
artifact；成功或失败退出均释放，stale lock 的人工恢复需独立检查。record 只允许上述文件/
目录集合并核对 manifest SHA、artifact SHA、逐文件清单和 COMPLETE；额外文件、缺失文件、
路径越界、symlink 或内容漂移均拒绝。

## 6. 公开隔离

内部参考模型必须满足：

- 不被 public queryset、serializer、template context、sitemap 或 cache key读取；
- 不注册任何 `post_save` 公开更新、新闻发布或 QQ 信号；
- 不存在“发布”“应用到赛事”“提升为 official”的 admin action；
- Django Admin 只允许有专门 view 权限的 staff 查看，禁止 add/change/delete；
- 下载结构化 artifact 也需要专门权限并写 `OperationLog`；
- 未登录、普通用户和公开 API 均返回不可见/不存在；
- public race page 不因内部观察新增查询或内容；
- collection 失败不能改变 `RaceEvent.status`、runner/result、revision 或 lifecycle control。

如以后需要人工采纳某条信息，必须另立 change，生成新的独立候选并重新执行来源权威、字段冲突、
审核、测试和发布授权；本阶段不提供 promotion 按钮或命令。

## 7. 来源特有限制

### 6.1 Sporting Life

- B0.1 不请求日期页；manifest URL 必须是含数字 race ID 的单场 result page；
- sponsor 名变化使用现有 alias/token 规则，但低相似度保持 ambiguous；
- `casualty.reason`、退赛和非正常完赛保留原始状态，不能自行改写为官方分类；
- stable race/horse ID 可作来源内 identity，不能自动跨 provider 合并。

### 6.2 ZEturf

- B0.1 不做 `R/C` 扫描；只请求 manifest 中已审核的单场 `date+R/C` URL；
- 必须同时核对日期、马场、赛事名和唯一 `R/C`；
- 既有 Grand Prix de Saint-Cloud 误配作为固定回归；
- 到达顺序是内部候选事实，不能成为 France Galop official。

### 6.3 HRN

- B0.1 不请求日期入口；只请求 manifest 中已审核的 track-day URL，route drift 必须 fail closed；
- trainer/jockey 合并单元格的启发式拆分必须保留 raw cell，并标记字段置信度；
- payout/also-rans 可能不完整，必须显式 `is_partial=true`；
- 没有可靠 draw/scratch 时留空，不能从行号、表格缺失或赔率推断；
- 重复 DOM 行按来源内 identity 去重，并保留 duplicate count。

## 8. 运行、HTTP 与保留

- 所有来源默认关闭，网络请求必须显式授权；
- 阶段 B0.1 不注册 Beat/Celery task，不使用任何 worker/queue；
- 网络 collect 与数据库 record 是两个命令：collect 可联网但数据库零写；record 必须离线读取
  已冻结 artifact；
- collect 使用唯一空输出目录、进程文件锁、每来源独立请求账本和 `COMPLETE` marker；崩溃或
  缺 marker 的 artifact 不能 record；
- 多日观察由 7 个逐日、逐来源、manifest-bound one-shot run 组成，不是无人值守 scheduler；
- 自动 selector/专用 worker 属阶段 B0.2，必须另行 spec/review/授权；
- raw HTML cache 默认建议保留 30 天，结构化 run/payload/receipt 与 hash 审计长期保留；
- 删除 raw cache 不删除 URL、hash、parser version、运行统计和结构化观察；
- 每个来源独立 run-local budget/circuit；一个来源失败不阻塞其他地区。

HTTP helper 必须在读取 body 前校验 `Content-Type`。仅允许大小写不敏感的 `text/html` 和
`application/xhtml+xml`，可带 `charset` 参数；header 缺失、重复冲突或其他 MIME 均在读取
body 前拒绝。并同时执行：

- `Content-Length <= 4 MiB`（存在时）；
- 流式逐 chunk 实际读取总量 `<=4 MiB`；
- redirect 最多 2 次，每一跳重新执行 HTTPS/host/path 合同；
- timeout、429/403、超限、类型错误只终止当前来源并记入账本/circuit。

B0.1 每个 manifest 只含一个来源；每个 event 最多请求一个 manifest URL，redirect hop 记入
request ledger 但不扩大 event 数。命令 `--max-requests` 不得超过 100，也不得超过 manifest
event 数；单请求 timeout 固定 15 秒，不做自动重试。连续 3 个 403/429/timeout/5xx 后终止本次
来源剩余请求并将其记为 `circuit_open`。下一来源使用独立命令、目录和账本，可继续运行。

请求账本、raw cache 和 manifest 全部位于本次不可变输出目录，不依赖容器内临时目录跨重启。

首版赛后观察窗口为赛事 `T+30 分钟至当地次日 23:59`。B0.1 不实现跨 run 持久网络预算，因此
“每场每来源每日最多一次”是运行手册和用户联网授权中的人工上限，不宣称程序强制；换 manifest
或输出目录再次执行技术上可触网，必须视为新的联网授权。命令只强制单 run request 上限并在
报告中按 event/source/day 标出重复运行。若以后需要无人值守或程序级每日限额，进入 B0.2
持久 budget/selector 设计。更早 racecard 或更高频率也属于独立扩展。

## 9. 验收

1. 三个现有 parser 的历史回归全部保持通过。
2. 内部观察可显示来源、时间、匹配证据、结构化差异和 partial/error。
3. 完全重放复用 payload，但每个 run 都有独立 receipt/provenance；仅语义变化追加 payload。
4. ambiguous/unmatched 不绑定赛事；同 payload 后续重新匹配追加 receipt。
5. collection 前后公开赛事、赛果、revision、新闻、QQ 计数和内容零变化。
6. 公开页面、API、sitemap、缓存和查询数不读取内部模型。
7. admin 无 add/change/delete/promotion 能力。
8. 阶段 B0.1 没有 Beat/task/queue 注册；无 collect 网络授权时零网络。
9. 单来源 403/429/timeout/DOM drift 只影响该来源。
10. 连续观察报告能按来源/地区/日期输出覆盖率、延迟、字段完整率、partial 和 mismatch。
11. legacy `official/is_confirmed` 不进入 reference payload/admin。
12. manifest/schema/DB snapshot/host/path/response size 任一越界均 fail closed。
