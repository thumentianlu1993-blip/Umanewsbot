# design：2026 赛事系列身份归并与双卡片治理

## 设计目标

新增“候选发现和人工审核适配层”，复用现有 `race_series_identity_review` 的生产写入引擎，不再
实现第二套事务、CAS、关系、回滚或 verifier。

## 现状与可复用能力

- `race_event_reconciliation.classify_historical_race_event_targets()` 已能把目标分类为
  `already_linked / exact_link / identity_conflict / status_conflict / missing_event`，但其跨系列
  发现只比较有限名称集合，输出不是面向本任务的四表工作簿。
- `race_series_identity_review` 已实现：
  - 正向 `merge_and_link` 和负向 `keep_independent/ignore_false_match`；
  - source/destination/target/event 全身份 SHA；
  - 依赖快照、同年冲突和人工锁；
  - 双 SHA approval、操作者一致性、事务锁、OperationLog、rollback ledger、apply/verify/rollback；
  - 保留 event 详情、公开 slug 和源系列审计关系。
- 既有正向动作要求不同动作的 source、destination、target、event 全部互斥，且源系列依赖只能是
  单个 annual event。本次探索的 226 条唯一名称匹配中，215 条当前可满足，11 条不满足。

## 组件

### 1. 新服务 `stable.services.race_series_identity_2026_review`

职责仅限：

- 在单次一致性数据库快照内加载 2026 targets/events/series/names/aliases 和详情摘要；
- 复用既有分类器得到基础分类；
- 生成确定性的审核行和依赖检查；
- 写出 canonical JSON、CSV 和 XLSX，并用原始 manifest 绑定全部机器文件和 canonical 行 payload；
- 读取用户定稿 XLSX，同时验证独立记录的原始 manifest SHA、其绑定文件、定稿 XLSX 字节 SHA、
  行集合、before/identity SHA 与 decision 契约；
- 把获准行转换为既有 decisions JSON，并携带审核时 target/event/source series/destination series
  四项 identity SHA；正向动作要求
  `engine_compatible`，负向动作交由既有引擎验证其精确系列对契约；field repairs 固定为空；
- 对 defer/未匹配行生成报告但不生成写动作。

不得在该服务中直接更新 ORM 对象。

### 2. 新管理命令 `review_2026_race_series_identities`

模式：

- 默认 `--output-dir`：只读导出快照与审核包；目录必须不存在；
- `--build-decisions --original-package-dir --expected-manifest-sha256 --reviewed-workbook
  --expected-workbook-sha256`：离线读取原始审核包与定稿副本并构建 decisions；
- 不提供 `--commit`。生产 prepare/apply/verify/rollback 继续调用既有
  `reconcile_race_series_identity_review` 命令。

这样把“发现候选”和“执行批准动作”分开，避免新命令绕过成熟写入门禁。

### 3. 审核包

目录至少包含：

- `snapshot.json`：as-of、生产 HEAD、总体计数、穷尽分类和逐行必要 identity；
- `review.json`：四类预期审核行、已关联只读清单和异常清单；
- `review.csv`：所有未关联行的平面镜像；
- `review.xlsx`：`审核说明 / 唯一名称匹配 / 同名多候选 / 无名称匹配 / 未举办 / 异常清单`；
- `manifest.json`：schema/generator、生产快照身份、每个机器文件 SHA、原始工作簿 SHA、canonical
  行 payload SHA、分区守恒。生成命令把 manifest SHA 单独输出并写入只读证据，不能以工作簿内
  的值作为信任根。

工作簿中的可编辑列仅为“唯一名称匹配”表的 `decision` 和 `review_note`；其他表全只读且只能
`defer`。回读定稿副本时，以原始 manifest 校验原始包，再把每个 sheet、行、顺序和机器列与原始
工作簿逐值比较，只允许上述两列不同，不能信任 Excel 公式计算结果。XLSX 使用仓库已有
`openpyxl==3.1.5`，不新增依赖。

## 候选与分桶

### 穷尽分类与基础分桶

以 2026 `HistoricalRaceEventTarget` 为分母：

先原样保存既有分类器的每个 `classification/reason`，至少覆盖：`already_linked`、
`linked_identity_mismatch`、`linked_status_incompatible`、`exact_link`、
`ambiguous_series_year_match`、`event_already_owned`、`series_year_region_mismatch`、
`status_incompatible`、`series_mismatch`、`ambiguous_name_match`、`no_series_year_event` 和
`not_held_target`。任何未知值归入异常并阻塞，不能丢弃或自动并入其他类别。

在该机器分区之上建立人工视图：

1. 已有关联且 target/event series 一致：`already_linked`，只计数，不进入待审表。
2. 未关联且同一 target series/year 已有唯一 event：沿用 `exact_link`，若存在应走既有关联流程，
   不作为双卡片合并。
3. 未关联且同地区同年名称唯一命中、series 不同：`unique_series_mismatch`。
4. 名称命中多个 event：`ambiguous_name_match`。
5. 无名称命中：`no_name_match`。
6. `not_held`：独立表。
7. 其余既有分类器输出：只读异常清单；非空时阻塞 decisions 构建，待用户确认并另行处置。

### 名称证据

正式分桶只使用现有分类器的核心精确名称集合，以保持 `226 / 11 / 162 / 2` 基线口径可解释。
`RaceSeriesName` 和 event alias 仅为“同名多候选/无名称匹配”行增加补充建议列，不得静默把这些行
改归“唯一名称匹配”。所有名称仅用于发现和排序，不成为自动批准条件。正向候选必须先锁定同地区、
同年；跨地区命中只作误匹配证据。

### 依赖检查

每条唯一候选预计算：

- source 是否只有一个 annual event；
- source 是否含 target/name/relation 依赖；
- destination 是否已有同年 event；
- source/destination 是否在同批其他正向候选中重复；
- 现有 `do_not_merge` 锁；
- target/event 是否已被其他对象拥有；
- 地区、年份、状态和详情字段一致性。

只有全部通过才标为 `engine_compatible=true`。该字段只是技术可执行性，不是用户批准。

### 动作与 evidence 契约

- 只有“唯一名称匹配”表允许 `merge_and_link / keep_independent / ignore_false_match / defer`；其余
  表本期只能 `defer`，因此不会伪造缺失的唯一 event 身份。
- `engine_compatible` 是正向归并兼容性，只对 `merge_and_link` 强制；负向动作不移动 event，不因
  source 含额外依赖、目标已有年度 event 或地区不一致而被该字段预先拒绝。其地区语义仍由既有
  引擎约束：跨地区误匹配只能使用其支持的 `ignore_false_match`。
- 所有非 `defer` 行都必须有非空 `review_note`。适配层把它写入 `evidence.summary`。
- `evidence.source_urls` 只能来自导出时已锁定的公开 URL 白名单，允许来源为 target/event/series
  `source_refs` 中键名为 `official / result / source_url / url / result_url` 的 HTTP(S) 字符串；不
  接受用户在工作簿中新增 URL。若没有至少一个合格 URL，该行只能 `defer`。
- URL 去重排序后进入机器行和原始 manifest；拒绝含用户信息、密码、非 HTTP(S) scheme 或明显凭据
  参数名（`token/key/secret/signature`）的 URL。

## 数据流

```text
生产只读快照
  -> 2026 target 全分母分类
  -> canonical JSON/CSV/XLSX + 文件 SHA
  -> 用户仅在唯一匹配表逐行审核
  -> 独立记录的原始 manifest SHA + 原始包全文件校验
  -> 定稿 XLSX 字节 SHA + 与原始工作簿逐单元格校验
  -> 仅 approved + engine-compatible 行转换为 decisions.json
  -> 既有 reconcile_race_series_identity_review prepare
  -> 新 manifest + 独立 approval
  -> 写前备份
  -> 既有 commit（单事务）
  -> 既有 verifier + 页面验收
```

## 并发与一致性

- 导出在 PostgreSQL repeatable-read 事务内读取；SQLite 测试验证确定性，不声称模拟 PostgreSQL 锁。
- 原始审核包由 manifest 锁定 snapshot/review/csv/original-workbook 和 canonical 行；manifest SHA 在
  生成时独立记录。工作簿定稿另锁定自身原始字节 SHA；回读时拒绝新增、删除、隐藏或重复数据行，
  并逐值核对机器列，公式单元格不以计算结果代替原值。
- decisions 生成后，既有 prepare 先比较工作簿携带的四对象 identity SHA，再从数据库读取完整
  before identity；生产 apply 再逐行锁定并复验。旧 decisions 不带审核 SHA 时保持既有兼容行为，
  本适配层生成的每一条非 defer decision 都必须携带四项 SHA。
- 任何新赛事导入、target 关联、series 名称/关系/人工锁变化都会导致 prepare 或 apply fail closed。
- 首批所有正向和负向动作只生成一个内部完全互斥的 manifest，并在单一事务中串行执行；若无法满足
  身份互斥或单批容量要求则停止，重新设计、复审和授权，不得在本方案内拆批。

## 模型与迁移

不新增模型、字段、索引或 migration。现有 `RaceSeriesRelation`、`manual_lock_flags`、
`HistoricalRaceEventTarget.event` 和 `OperationLog` 足够表达结果。

## 性能

- 规模约 1,085 targets、1,448 个 2026 events 和约万级全部年度 events，可在内存构建索引；禁止逐行
  ORM 查询。
- series/name/alias/dependency 统一批量加载，工作簿生成不访问数据库。
- 测试为查询数设置上限，避免 401 行产生 N+1。

## 发布与回滚

- 候选导出和工作簿阶段不部署、不写库。
- 代码发布与数据 apply 分开授权；部署新只读命令不会自动执行。
- 数据 apply 前执行 custom-format PostgreSQL 备份并通过 `pg_restore -l`。
- 首批全部动作使用单一 manifest 和单事务，不拆 shard。使用既有 rollback ledger 精确恢复
  target/event/series relation/locks；全库备份是最终恢复点。
- 旧源系列不删除，因此回滚不依赖重建系列。

## 关键取舍

1. 完整盘点 401 条探索基线，但首批只写经人工批准且现有引擎兼容的高置信项。
2. 不扩展现有 apply 引擎来吞掉 11 条特殊候选；先把事实和审核结论做完整。
3. XLSX 是人工界面，JSON/CSV 是机器真相；任何格式间集合不一致都阻塞。
4. 生产成功标准包含数据守恒与真实页面连续性，不以 `MERGED_INTO` 行数代替验收。

## 导出字段白名单

本地审核包只允许包含：target/event/source/destination series 的 ID 与 identity SHA、地区、年度、
名称、日期、马场、等级、场地、距离、公开/解析状态、依赖布尔值、候选 ID、经上述规则清洗的公开
来源 URL、分类、decision 和 review_note。完整 `source_refs`、`manual_lock_flags`、`module_statuses`、
`field_provenance`、notes、原始详情 payload、缓存路径、请求头、Cookie、凭据及数据库连接信息不得
导出；它们只在服务器端参与 identity/依赖 SHA。序列化测试必须递归拒绝敏感键和凭据模式。
