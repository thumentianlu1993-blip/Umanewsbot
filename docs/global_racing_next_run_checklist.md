# 全球赛马数据库下一轮执行检查表

日期：2026-06-30

用途：给后续新会话执行完整最近 60 天抓取时作为开跑检查页。详细命令和背景仍以 `docs/global_racing_full_crawl_runbook.md`、`docs/global_racing_sync_manifest.md` 和 `docs/global_racing_database_handoff.md` 为准。

## 总原则

- 顺序固定为：香港 HKJC -> 英国 Sporting Life -> 法国 Geny -> 美国 Horse Racing Nation。
- 每个地区先 `plan-only`，再按 plan 输出的小批次 dry-run。
- 每个地区执行具体 batch 前，先用 `render_global_racing_batch_command --plan-file ... --all-batches --output-dir runtime/global_racing_import/<region>` 渲染完整批次命令清单；执行单个批次时可用 `--batch N`。优先按输出中的 `tee_command_line` 执行并保存 dry-run JSON，避免手工复制 `race_ids`、`race_urls` 或 `partants_urls` 出错，也避免覆盖批次文件。
- 渲染命令清单若误放入审计目录，`audit_global_racing_import_outputs` 会按 artifact 类型忽略；但文件名仍建议使用 `*-commands.json`，不要伪装成 plan 或 batch 输出。
- dry-run 和 proof 不得写正式表；只有用户显式确认后才能加 `--commit`。
- 任何生产 `--commit` payload 都必须包含 `completion.is_complete=true` 的严格布尔完成证明；缺失 completion、`null`、字符串或其他非布尔值必须视为未验证。
- 任何生产 `--commit` payload 的 `completion` 都必须包含可解析为整数的 `unique_horses_found` 与 `horse_profiles_fetched`。
- 即使 `is_complete=true`，若 `stop_reason` 不是 `complete`，或 `horse_profiles_fetched` 少于 `unique_horses_found` 且没有认可的行内详情来源，也必须视为未验证。
- 任何生产 `--commit` payload 都必须有非空 `coverage_stats.races`、`entries`、`results` 和 `horses`。
- 任一地区出现 `completion.is_complete=false`、`429`、登录跳转、请求超时、空输出、锁未释放或审计阻断时，停止该地区并先排查。
- 当前 proof JSON 只证明入口和 parser/importer 可用，不能作为完整最近 60 天抓取或 commit 候选。

## 开跑前共同检查

- 确认当前代码版本、工作树和部署位置。
- 执行 `python server/manage.py check`。
- 执行 `python server/manage.py makemigrations --check --dry-run`。
- 执行 `python server/manage.py migrate --plan`，确认待迁移项符合预期。
- 生产写库前备份数据库，并检查 `ExternalDataImportRun` 是否有 `started` 状态、`ExternalDataImportLock` 是否有未释放锁。
- 为每个地区建立独立输出目录，审计 JSON 不要写进被审计的输入目录。

## 1. 香港 HKJC

当前边界：

- 已有生产前 dry-run 进度为前 `120/144` 场，未 commit。
- `2026-06-30` 已恢复香港慢速真实 dry-run 试跑；最新 plan 变为 `146` 场、`8` 批，已不同于历史 `144` 场。
- 已完成最新 plan 中前两场 `HK20260627ST02,HK20260627ST03` 的慢速 dry-run，输出 `runtime/global_racing_import/hkjc-20260630/hkjc-batch1-races-001-002-dryrun-20260630.json`，`completion.is_complete=true`、`horse_profiles_fetched=28`、`30/30` 请求返回 `200`，未 commit。

下一步：

1. 运行最新 `--recent-days 60 --plan-only`。
2. 因最新 plan 已确认不是历史 `144` 场，后续按最新 `146` 场 plan 重新切批；不要直接沿用旧 `--skip-races 120`。
3. 每批使用 `--limit-races` 控制小批，`--limit-horses` 必须覆盖本批唯一马匹数。

必须收集：

- plan 总比赛数、批次数、输出文件路径。
- 每批 `coverage_stats`、`completion`、`horse_profiles_fetched`、请求数和失败摘要。
- 若进入 commit 讨论，需备份路径、锁检查、健康检查和用户显式确认。

停止条件：

- 如果 plan 总量或停点与历史 `120/144` 不一致，先记录差异并暂停确认。
- 任一批次出现非 `200`、`completion.is_complete=false`、请求超时、空输出、锁未释放或健康检查失败，立即暂停。

## 2. 英国 Sporting Life

当前 proof：

- 英国赛场 allowlist 后最近 60 天 plan 曾为 `35` 场、`7` 批。
- racecard dry-run 已覆盖 `35/35`；少量全量 profile proof 已证明闭环可用。
- 全部涉及马匹 profile 尚未补齐，未生产 commit。

下一步：

1. 运行最新 `import_uk_external_data --recent-days 60 --plan-only --batch-size 5`。
2. 用 `render_global_racing_batch_command` 从 plan 文件渲染指定 batch 的 `race_urls` 精确 dry-run 命令。
3. 完整批次不要使用过小的 `--limit-horses`；如设置，必须不小于本批唯一马匹数。

必须收集：

- plan 中英国赛场过滤依据和 `race_urls` 清单。
- 每批 entries、results、唯一 horse、`horse_profiles_fetched`。
- 每批 `completion.is_complete=true`。

停止条件：

- plan 混入非英国赛场。
- 任何批次 profile 未补齐却被当作完整批次。

## 3. 法国 Geny

当前 proof：

- France Galop today 可用，但历史入口受登录限制。
- 最近 60 天历史窗口以 Geny 为主。
- Geny 已证明 date -> partants -> results -> horse profile 链路；曾触发过 `429`，建议至少 `10` 秒/请求。

下一步：

1. 运行最新 `import_france_external_data --source geny --recent-days 60 --plan-only --batch-size 5`。
2. 用 `render_global_racing_batch_command` 从 plan 文件渲染指定 batch 的 `partants_urls` 低频精确 dry-run 命令。
3. 独立 horse profile 需要显式设置 `--limit-horses M`，且 M 必须覆盖本批唯一马匹数；若用行内详情替代 profile，必须文档化字段覆盖边界。

必须收集：

- plan 中 Geny race/partants URL 清单。
- 每批 partants、results、horse profile 请求证据。
- `429`、登录跳转或 partial 输出的处理结论。

停止条件：

- 出现 `429` 或登录跳转。
- `completion.is_complete=false`。
- profile 或等价详情字段覆盖不足。

## 4. 美国 Horse Racing Nation

当前 proof：

- Equibase 返回防护页，DRF 为 JS 应用壳。
- 第一版以 HRN 为主，已证明 date/track-day、runner/result table 和 horse profile 可解析。
- 完整 60 天日期/赛场覆盖策略尚未完成。

下一步：

1. 运行最新 `import_us_external_data --recent-days 60 --seed-track churchill-downs --plan-only --batch-size 5`。
2. 用 `render_global_racing_batch_command` 从 plan 文件渲染指定 batch 的 `race_ids` 精确 dry-run 命令。
3. `--limit-tracks` 只能用于 proof 或探索，不得用于完整 commit 候选 plan。
4. `--limit-horses M` 必须覆盖本批唯一马匹数。

必须收集：

- plan 的日期范围、seed track、发现赛场和 `race_ids`。
- 每批 `track_days_found`、`track_days_fetched`、entries、results、horse profile。
- 所有涉及马匹 profile 覆盖证明。

停止条件：

- plan 只覆盖单个 seed track 且未说明日期/赛场覆盖口径。
- 使用了 `--limit-tracks` 作为完整 commit 候选 plan。
- horse profile 覆盖不足。

## 每地 commit 候选门禁

每个地区都必须先通过离线审计：

```bash
python server/manage.py audit_global_racing_import_outputs \
  --input-dir runtime/global_racing_import/<region> \
  --pattern "*.json" \
  --fail-on-incomplete
```

进入 commit 讨论前，审计输出必须满足：

- `commit_candidate_ready=true`
- `blocking_reasons=[]`
- `source_count=1`
- `plan_file_count>=1`
- `batch_file_count>=1`
- `planned_item_count>=1`
- `incomplete_file_count=0`
- `empty_plan_request_file_count=0`
- `non_success_plan_response_file_count=0`
- `empty_batch_request_file_count=0`
- `non_success_batch_response_file_count=0`
- `empty_batch_coverage_file_count=0`
- `incomplete_horse_detail_file_count=0`
- `missing_planned_item_count=0`
- `extra_covered_item_count=0`
- `duplicate_planned_item_count=0`
- `duplicate_covered_item_count=0`
- `would_write_formal_table_file_count=0`

## 本轮停止点

完整目标只有在四地最新 60 天 plan、所有 dry-run 批次、所有涉及马匹详情、离线审计、生产 commit 门禁和文档回写都完成后，才能标记完成。否则保持目标继续，不要把 proof-only 或 fixture 测试当成完成证据。
