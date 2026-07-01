## Context

当前未知马名识别依赖片假名候选规则和正式术语库。该方式对新闻正文中的普通片假名词误报较多，也无法稳定识别未进入正式术语库的真实马名。用户已确认短期目标是先抓取近两年 netkeiba 相关赛马数据，保存可用全字段，并以严格限速方式逐步建立本地赛马数据库。

`keibascraper` 可按 `race_id` 抓取出走表、赛果、赔率，并可按 `horse_id` 抓取马匹血统和出走履历；它不提供按马名搜索的实时接口，因此本项目应把它用作离线/低频导入工具，而不是新闻处理链路中的同步查询依赖。

## Goals / Non-Goals

**Goals:**

- 建立本地外部赛马数据缓存，覆盖近两年 netkeiba 赛事、出走、赛果、赔率、马匹血统和履历数据。
- 保存 `keibascraper` 返回的所有结构化字段，并额外保留原始 payload 和来源标识，便于后续调整模型字段。
- 形成可查询的马名索引，用于后续降低未知马名误报和漏报。
- 提供手动触发、dry-run、分月执行、断点续跑、失败重试和导入统计。
- 严格控制请求速率，避免生产任务对 netkeiba 造成集中压力。

**Non-Goals:**

- 本 change 不直接改变自动发布、AI 改写、未知马名校验或术语候选发现规则。
- 本 change 不承诺抓取 netkeiba 全历史数据；首版范围是近两年。
- 本 change 不把 netkeiba 抓取放入新闻入库或翻译同步路径。
- 本 change 不提供面向公开用户的数据查询页面。

## Decisions

### 1. 使用适配层包装 `keibascraper`

实现新增 `stable.services.external_horse_data` 或同类服务层，对外暴露本项目自己的导入接口，内部调用 `keibascraper.load()` 与 `keibascraper.race_list()`。

原因：

- 避免业务代码直接依赖第三方库返回结构。
- 便于替换为本项目自写解析器、JRA-VAN、JBIS 或本地文件导入。
- 便于统一限速、错误处理、重试和日志。

备选方案：直接在管理命令中调用 `keibascraper`。该方案实现快，但会把外部依赖、限速和持久化逻辑耦合在命令中，不利于 Celery 任务复用。

### 2. 结构化字段和原始 payload 同时保存

新增模型时按 `keibascraper` 的数据类型拆分：

- `ExternalRace`
- `ExternalRaceEntry`
- `ExternalRaceResult`
- `ExternalRaceOdds`
- `ExternalHorse`
- `ExternalHorseHistory`
- `ExternalHorseAlias` 或等价马名索引表
- `ExternalDataImportRun`
- `ExternalDataImportError`

每个数据表除结构化字段外，应包含：

- `source`
- `external_id` 或组合唯一键
- `raw_payload`
- `fetched_at`
- `last_seen_at`

原因：

- 结构化字段便于查询马名和比赛。
- 原始 payload 允许后续字段扩展时回放，不必重新访问外部站点。
- 来源字段允许未来混合 netkeiba、JBIS、JRA-VAN 或本地 CSV。

备选方案：只存原始 JSON。该方案迁移轻，但无法高效查询马名、horse_id、race_id，也不方便做唯一约束。

### 3. 首轮按月份分批导入近两年 race_id

管理命令默认生成从当前月份往前 24 个月的月份列表，逐月调用 `race_list(year, month)`，再对每个 `race_id` 抓取 `entry`、`result`，并按配置决定是否抓取 `odds`。从 `entry/result` 中收集 `horse_id` 后，再按 horse_id 抓取 `horse` 与 `history`。

原因：

- 近两年足以覆盖当前新闻高频出现马名。
- 按月份切分天然适合暂停、恢复和生产灰度。
- 先通过出走/赛果收集 horse_id，比猜马名或实时搜索更稳定。

备选方案：按马名在线搜索。`keibascraper` 不提供该接口，且新闻链路同步搜索风险高。

### 4. 强限速和显式执行

导入必须默认由人工命令或明确 Celery 任务触发，不加入默认 beat 全量调度。配置项建议：

- `EXTERNAL_HORSE_DATA_IMPORT_ENABLED=false`
- `EXTERNAL_HORSE_DATA_ALLOW_NETWORK=false`
- `EXTERNAL_HORSE_DATA_LOOKBACK_MONTHS=24`
- `EXTERNAL_HORSE_DATA_REQUEST_INTERVAL_SECONDS=5`
- `EXTERNAL_HORSE_DATA_JITTER_SECONDS=2`
- `EXTERNAL_HORSE_DATA_MAX_RACES_PER_RUN=30`
- `EXTERNAL_HORSE_DATA_MAX_HORSES_PER_RUN=100`
- `EXTERNAL_HORSE_DATA_FETCH_ODDS=false`
- `EXTERNAL_HORSE_DATA_FETCH_HORSE_DETAIL=true`

请求间隔必须由本项目服务层控制，不能只依赖第三方库内部 sleep。生产首跑建议使用更保守的 8-10 秒间隔和小批量。

同一 `source` 在同一时间只允许一个导入运行执行真实外部请求。管理命令和 Celery 任务应通过数据库锁、运行状态检查或等价互斥机制避免多个 worker 并发绕过单进程 sleep，防止请求被并发放大。

### 5. 幂等 upsert 与断点续跑

每个外部记录使用来源和外部 ID 或组合键唯一约束：

- race：`source + race_id`
- entry/result/odds：`source + race_id + horse_number` 或第三方返回 id
- horse：`source + horse_id`
- history：`source + horse_id + race_id + horse_number`

导入运行记录保存：

- 目标月份、任务参数、状态
- 当前处理到的 race_id / horse_id
- 成功、跳过、失败计数
- 启动和结束时间

失败记录保存异常类型、目标类型、目标 ID、错误摘要和重试次数。重跑时已成功记录必须跳过或更新，不得重复插入。

### 6. 马名索引从外部数据表派生

`ExternalHorseAlias` 由以下来源填充：

- `ExternalRaceEntry.horse_name`
- `ExternalRaceResult.horse_name`
- `ExternalHorse` 的主马名字段，如后续可从页面解析到
- 未来可从 JBIS、JRA-VAN 或人工导入补充

首版索引至少包含 `source`、`external_horse_id`、`name_ja`、`normalized_name`、`confidence`、`first_seen_at`、`last_seen_at`。后续未知马名识别可先查询该索引，再决定是否硬性保护或只进入候选池。

单独按 `horse_id` 导入时，如果 `horse` 页面或履历数据无法提供主马名，系统可以只保存马匹详情和履历，不强行创建马名索引；管理命令应允许传入可选 `--horse-name`，用于人工已知马名的单马补抓场景。只有存在可信 `horse_name` 时才写入 `ExternalHorseAlias`。

导入统计需要输出覆盖率信号：比赛数、出走记录数、赛果记录数、唯一 `horse_id` 数、唯一日文马名数、缺失 `horse_id` 或 `horse_name` 的记录数。后续判断本地马名库是否足够可用时，以这些统计为依据。

## Risks / Trade-offs

- [外部站点负载或条款风险] → 默认关闭网络导入；仅人工执行；强制限速、随机抖动、小批量、可暂停；文档明确使用前需确认合规。
- [页面结构变化导致解析失败] → 所有第三方调用经过适配层；失败写入 `ExternalDataImportError`；导入失败不影响新闻主链路。
- [赔率和 horse detail 增加请求量] → `odds` 默认可关闭；horse detail 设置单批上限；首轮可先导入 entry/result，再逐步补全。
- [多 worker 并发放大请求] → 同一来源导入运行加互斥保护；文档要求生产单任务执行。
- [数据量增长] → 使用唯一约束和索引；首版限定近两年；生产导入前先估算记录量并备份数据库。
- [第三方库依赖不稳定] → 包装在服务层；测试中 mock 外部调用；保留未来替换解析器的边界。

## Migration Plan

1. 新增模型和迁移，仅创建表和索引，不启动网络导入。
2. 新增配置并保持生产默认关闭。
3. 本地使用 mock / 少量真实样本验证 dry-run、限速、upsert、断点续跑、依赖 import 和覆盖率统计。
4. 生产部署迁移前备份数据库。
5. 生产先执行 dry-run 或单月小批量导入，确认失败率、耗时和记录量。
6. 再按月逐步补齐近两年数据。

回滚策略：

- 停止导入：关闭配置或不再触发管理命令 / Celery 任务。
- 代码回退：新表不参与主链路，保留数据不影响现有功能。
- 数据清理：如需清理，可按 `source` 和 import run 删除外部数据表记录。

## Open Questions

- 生产首轮是否抓取 `odds`，还是先只抓 `entry/result/horse/history`。
- `keibascraper` 在生产网络环境下对 netkeiba 的成功率和实际限流表现。
- 是否需要为导入任务增加后台只读进度页，还是首版只通过管理命令和日志验收。
