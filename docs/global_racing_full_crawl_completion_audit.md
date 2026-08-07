# 全球赛马数据库完整爬取完成审计

日期：2026-06-27

关联能力规格：`旧规格流程/specs/real-global-racing-data-ingestion/spec.md`

## 结论

当前仓库和运行记录只能证明四地真实接入 proof 已成立，不能证明“香港、英国、法国、美国最近 2 个月赛事与所有涉及马匹详情已完整抓取完成”。

本审计用于下一轮完整大量爬取会话启动前恢复上下文。后续会话不得把本轮 proof、少量 dry-run、fixture commit 或局部 profile proof 误认为完整目标已完成。

## 当前主树同步状态

`2026-06-27` 当前主工作树 `/Users/mentianlu/Code/umanews` 已同步恢复所需的代码、fixtures、旧规格流程 产物、proof JSON 和文档，但这些同步内容仍是未提交工作树差异，且本地 `main` 仍落后 `origin/main`。审查和提交前应先阅读：

- `docs/global_racing_sync_manifest.md`
- `docs/global_racing_change_partition.md`
- `docs/global_racing_database_handoff.md`
- `docs/global_racing_next_run_checklist.md`
- `docs/global_racing_full_crawl_runbook.md`

当前主树已完成的本地验证包括：

- `python server/manage.py check`
- `python server/manage.py test stable`，`347` 项通过
- 外部缓存底座、HKJC、UK、France、US importer 和 global racing audit 相关局部测试
- `python server/manage.py makemigrations --check --dry-run`
- `python server/manage.py migrate --plan`
- `旧规格流程 validate --all`
- proof-only 审计通过，且同一组 proof JSON 按完整 commit 候选口径会被正确阻断
- `git diff --check`

这些验证只证明当前主树可作为后续完整大量爬取会话的恢复基线；不改变本审计结论，也不证明最近 60 天完整抓取、所有马匹详情覆盖或生产 commit 已完成。

## 完整目标拆解

完整目标至少需要逐项证明：

1. 香港、英国、法国、美国均有可重复执行的真实数据入口。
2. 每个地区均覆盖最近 2 个月赛事列表，而不是只覆盖单日、少量赛场或少量比赛。
3. 每场比赛均抓到出马、赛果和唯一马匹集合。
4. 每个涉及马匹均抓到可用马匹详情，或记录来源限制下的等价行内详情字段。
5. 抓取过程低频、可中断、可审计，不加入 Celery Beat 持续调度。
6. 如执行生产写库，必须先完成备份、完整 dry-run 汇总、锁检查、健康检查和用户显式确认；生产 `--commit` payload 必须包含 `completion.is_complete=true` 的严格布尔完成证明，缺失 completion、`null`、字符串或其他非布尔值不得写库；`completion` 还必须包含可解析为整数的 `unique_horses_found` 与 `horse_profiles_fetched`；若 `stop_reason` 不是 `complete`，或 `horse_profiles_fetched` 少于 `unique_horses_found` 且没有认可的行内详情来源，也不得写库；若 `coverage_stats.races`、`entries`、`results` 或 `horses` 任一为 `0`，也不得写库。
7. 完成后要有表计数、run_id、coverage_stats、completion、请求数量、失败摘要和停止点证据。
8. 每地 dry-run 批次 JSON 必须先通过 `audit_global_racing_import_outputs --fail-on-incomplete` 离线审计，证明存在有效且完整的 dry-run plan-only 文件和至少一个非 plan dry-run 批次，所有文件包含非空 `source` 且属于同一来源，并且没有 incomplete、不可解析、非 dry-run、受限 plan、马匹详情覆盖不足、重复计划项、重复覆盖项、任一 dry-run JSON 显式会写正式表、plan 中未覆盖的批次，或覆盖了 plan 外项目的批次混入 commit 候选；审计 JSON 的 `blocking_reasons` 必须为空。

## 当前证据强度

| 地区 | 当前最强证据 | 已证明 | 未证明 |
| --- | --- | --- | --- |
| 香港 | 生产前 6 个 plan-only 批次拆成 24 个小批次 dry-run，覆盖 `120` 场、`1522` 条 entries/results 和 `1522` 个 horse profile 请求 | HKJC HTML 入口、批次执行、profile 补抓、重试与 dry-run 安全边界可用 | 最近 60 天 `144` 场中的剩余 `24` 场未作为正式进度完成；未执行真实网络生产 commit |
| 英国 | 过滤后英国赛场 plan-only 为 `35` 场；racecard dry-run 达到 `35/35`；两组 profile proof 分别 `46/46`、`59/59`；2026-06-27 低频复核精确 `race_urls` 入口返回 `200`，输出 `runtime/global_racing_import/proof-20260627/uk/uk-race-url-proof.json`；三地 proof-only 审计 `runtime/global_racing_import/proof-20260627-audit.json` 通过；本地 TDD 已证明 `race_urls` 精确批次可幂等写入 `External*` 表 | Sporting Life 入口、英国赛场过滤、`race_urls` 精确批次、全量 profile proof 机制、本地 commit 写入路径可用 | `35` 场所有涉及马匹 profile 未全部补齐；未执行生产真实网络 commit |
| 法国 | France Galop 当日 smoke；Geny 60 天窗口小批 dry-run 覆盖 `5` 场、`57` entries、`52` results、`54` horses；Geny 独立 profile 单页 proof 已确认；2026-06-27 低频复核精确 `partants_urls` 入口返回 `200`，输出 `runtime/global_racing_import/proof-20260627/france-geny/france-geny-partants-proof.json`；三地 proof-only 审计 `runtime/global_racing_import/proof-20260627-audit.json` 通过；本地 TDD 已证明 Geny `partants_urls` 精确批次可幂等写入 `External*` 表 | France Galop today、Geny 历史公开页、显式限量 horse profile proof、429 安全停止、本地 commit 写入路径可用 | 最近 2 个月法国赛事未完整枚举；所有涉及马匹 profile 未全量补齐；未执行生产真实网络 commit |
| 美国 | HRN 60 天窗口小批 dry-run 覆盖 `5` 场、`37` entries、`20` results、`37` horses、`10` profiles；2026-06-27 低频复核精确 `race_ids` 入口返回 `200`，输出 `runtime/global_racing_import/proof-20260627/us-hrn/us-hrn-race-id-proof.json`；三地 proof-only 审计 `runtime/global_racing_import/proof-20260627-audit.json` 通过；本地 TDD 已证明 HRN `race_ids` 精确批次可幂等写入 `External*` 表 | HRN 日期索引、track-day、runner/result table、horse profile、本地 commit 写入路径可用 | 最近 2 个月全美日期/赛场覆盖策略未完成；Equibase 不可用；未执行生产真实网络 commit |

## 命令能力差距

### HKJC

`import_hkjc_external_data` 已支持：

- `--plan-only`
- `--skip-races`
- `--race-ids`
- `--limit-races`
- `--limit-horses`
- `--commit`

下一轮应先重跑生产 plan-only，确认当时最近 60 天比赛数量，再从已确认停点之后继续。此前正式进度停在前 `120/144` 场 dry-run；停点后的 `hkjc-batch7a/7b` 文件不作为正式进度依据。

### 英国

`import_uk_external_data` 已支持显式 `--commit`，默认仍为 dry-run。当前本地 TDD 证明范围为 Sporting Life 精确 `race_urls` 完整小样本 payload 的幂等写入：`ExternalRace / ExternalRaceEntry / ExternalRaceResult / ExternalHorse / ExternalHorseAlias`、`ExternalDataImportRun` 成功记录和单来源锁释放；若 `completion.is_complete=false`，commit 会被拒绝。

英国命令已支持：

- `--plan-only`
- `--batch-size`
- `--race-urls`
- `--limit-horses`
- `--commit`

下一轮应优先使用过滤后 plan-only 输出的 `race_urls`，按小批次补齐所有涉及马匹 profile。不要再使用未过滤的 `47` 场 / `10` 批口径；不得把本地 fixture/mock commit 测试视为生产写入证据。

### 法国

`import_france_external_data` 已支持显式 `--commit`，默认仍为 dry-run。当前本地 TDD 证明范围为 Geny 精确 `partants_urls` 完整小样本 payload 的幂等写入：`ExternalRace / ExternalRaceEntry / ExternalRaceResult / ExternalHorse / ExternalHorseAlias`、`ExternalDataImportRun` 成功记录和单来源锁释放；若 `completion.is_complete=false`，commit 会被拒绝。

法国 Geny 命令已补齐完整大量爬取前的本地批次能力：

- `--plan-only`
- `--batch-size`
- `--skip-races`
- `--partants-urls`
- `--limit-horses`（显式传入时才请求 Geny 独立 horse profile；默认 dry-run 不额外抓 profile）

下一轮若要生产写库，仍必须先实际运行最新 60 天 plan-only。后续小批 dry-run 优先使用 plan 输出的 `partants_urls` 执行精确批次，避免每批重复扫描日期页；`--skip-races` 只作为恢复兼容入口。如需补独立 profile，则按每批唯一马匹数显式设置 `--limit-horses`，并确认 `horse_profiles_fetched` 与本批目标一致。之后再执行备份、锁检查、健康检查和用户显式确认；不得把本地 fixture/mock commit 测试视为生产写入证据。

### 美国

`import_us_external_data` 已支持显式 `--commit`，默认仍为 dry-run。当前本地 TDD 证明范围为 HRN 精确 `race_ids` 完整小样本 payload 的幂等写入：`ExternalRace / ExternalRaceEntry / ExternalRaceResult / ExternalHorse / ExternalHorseAlias`、`ExternalDataImportRun` 成功记录和单来源锁释放；若 `completion.is_complete=false`，commit 会被拒绝。

美国命令已补齐完整大量爬取前的本地批次能力：

- `--plan-only`
- `--batch-size`
- `--skip-races`
- `--race-ids`

下一轮若要生产写库，仍必须先实际运行最新 60 天 plan-only。后续小批 dry-run 优先使用 plan 输出的 `race_ids` 执行精确批次，避免每批重复扫描日期索引和早期 track-day；`--skip-races` 只作为恢复兼容入口。完成 dry-run 汇总后，再执行备份、锁检查、健康检查和用户显式确认；不得把本地 fixture/mock commit 测试视为生产写入证据。

## 下一轮建议执行顺序

### 1. 生产安全预检

```bash
cd /opt/umanewsbot
git rev-parse --short HEAD
docker compose -f docker-compose.prod.lowcost.yml ps
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py shell -c "from stable.models import ExternalDataImportRun, ExternalDataImportLock; print('started_runs', ExternalDataImportRun.objects.filter(status='started').count()); print(list(ExternalDataImportLock.objects.values('source','racing_region','locked_by_run_id','acquired_at')))"
curl -sS -o /dev/null -w "local_healthz=%{http_code}\n" http://127.0.0.1/healthz/
```

### 2. 备份

```bash
cd /opt/umanewsbot
mkdir -p backups/db
backup_path="backups/db/pre-global-racing-full-crawl-$(date +%Y%m%d_%H%M%S).sql.gz"
docker compose -f docker-compose.prod.lowcost.yml exec -T db pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" | gzip > "$backup_path"
gzip -t "$backup_path"
echo "$backup_path"
```

### 3. 香港补剩余 dry-run

先重跑 plan-only：

```bash
docker compose -f docker-compose.prod.lowcost.yml run --rm --no-deps web python manage.py import_hkjc_external_data --recent-days 60 --end-date YYYY-MM-DD --plan-only --limit-races 20 --max-requests 120 --allow-network
```

再按 plan 输出继续剩余批次。若仍为 `144` 场并且前 `120` 场已作为正式进度接受，则从 `--skip-races 120` 开始；否则以最新 plan 重新确认。

### 4. 英国补全 profile dry-run

先生成过滤后的计划：

```bash
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true UK_IMPORT_REQUEST_INTERVAL_SECONDS=2 UK_IMPORT_MAX_REQUESTS_PER_RUN=160 python server/manage.py import_uk_external_data --recent-days 60 --end-date YYYY-MM-DD --plan-only --batch-size 5 --allow-network
```

再用 plan 输出的 `race_urls` 小批运行。补 profile 时不要设置 `--limit-horses`，或设置为不小于该批唯一马匹数：

```bash
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true UK_IMPORT_REQUEST_INTERVAL_SECONDS=2 UK_IMPORT_MAX_REQUESTS_PER_RUN=200 python server/manage.py import_uk_external_data --race-urls URL1,URL2,URL3,URL4,URL5 --allow-network
```

### 5. 法国完整 dry-run 和生产 commit 门禁

先生成 60 天批次计划：

```bash
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true FRANCE_IMPORT_REQUEST_INTERVAL_SECONDS=10 FRANCE_IMPORT_MAX_REQUESTS_PER_RUN=80 python server/manage.py import_france_external_data --source geny --recent-days 60 --end-date YYYY-MM-DD --plan-only --batch-size 5 --allow-network
```

再按 plan 输出低频小批 dry-run：

```bash
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true FRANCE_IMPORT_REQUEST_INTERVAL_SECONDS=10 FRANCE_IMPORT_MAX_REQUESTS_PER_RUN=120 python server/manage.py import_france_external_data --source geny --partants-urls URL1,URL2,URL3,URL4,URL5 --limit-horses M --allow-network
```

`--skip-races` 仍可用于兼容旧批次口径，但完整大量爬取应优先用 `--partants-urls`，让每批只请求目标 partants/results 和目标 horse profile。

若要生产写库，当前命令已有 `--commit`，但仍需在执行前确认：

- 最新 60 天 Geny plan 和拆批 dry-run 汇总完整
- 如本批要求独立 profile，则 `horse_profiles_fetched` 与目标唯一马匹数一致
- 429 / partial dry-run 不进入 commit
- 备份路径、锁检查、健康检查和用户显式确认齐全

### 6. 美国完整 dry-run 和生产 commit 门禁

先生成 60 天批次计划：

```bash
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true US_IMPORT_REQUEST_INTERVAL_SECONDS=5 US_IMPORT_MAX_REQUESTS_PER_RUN=240 python server/manage.py import_us_external_data --recent-days 60 --end-date YYYY-MM-DD --seed-track churchill-downs --plan-only --batch-size 5 --allow-network
```

再按 plan 输出低频小批 dry-run：

```bash
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true US_IMPORT_REQUEST_INTERVAL_SECONDS=5 US_IMPORT_MAX_REQUESTS_PER_RUN=120 python server/manage.py import_us_external_data --race-ids HRN_track_YYYY-MM-DD_N,HRN_track_YYYY-MM-DD_N --limit-horses M --allow-network
```

`--skip-races` 仍可用于兼容旧批次口径，但完整大量爬取应优先用 `--race-ids`，让每批只请求目标 track-day 和目标 horse profile。`--limit-tracks` 只能用于 proof 或探索；完整爬取 commit 候选 plan 不能带该限制，否则离线审计会以 `limited plan ...` 阻断。若要生产写库，当前命令已有 `--commit` 和幂等写入测试，但仍需先完成最新 plan、所有 dry-run 批次汇总、备份、锁检查、健康检查和用户显式确认。

## 完成判定

不得使用以下证据宣称完整目标完成：

- 单场 smoke
- 少量 `limit-races=5` dry-run
- 仅 racecard 覆盖而没有全量 profile
- fixture commit
- `completion.is_complete=false` 的批次
- 未过滤海外赛场的英国 `47` 场计划
- 未进入 commit 门禁的 dry-run

可以作为完成证据的是：

- 每地最新 plan-only 总量和已执行批次清单一致，且没有重复计划项或重复覆盖项
- 每地 `audit_global_racing_import_outputs --fail-on-incomplete` 输出 `commit_candidate_ready=true`、`blocking_reasons=[]`、`source_count=1`、`missing_source_file_count=0`、`plan_file_count>=1`、`batch_file_count>=1`、`planned_item_count>=1`、`incomplete_plan_file_count=0`、`non_dry_run_plan_file_count=0`、`limited_plan_file_count=0`、`empty_plan_request_file_count=0`、`non_success_plan_response_file_count=0`、`empty_batch_request_file_count=0`、`non_success_batch_response_file_count=0`、`empty_batch_coverage_file_count=0`、`incomplete_horse_detail_file_count=0`、`duplicate_planned_item_count=0`、`duplicate_covered_item_count=0`、`would_write_formal_table_file_count=0`、`missing_planned_item_count=0` 且 `extra_covered_item_count=0`
- 每个批次 `completion.is_complete=true`
- 每地请求证据、失败摘要和停止原因已归档
- 每地所有涉及马匹 profile 或等价详情字段已覆盖，且不存在 `incomplete horse details ...` 阻断原因
- 如写库，生产表计数、run_id、锁释放、健康检查和备份路径齐全
- 文档明确记录完整爬取完成时间、范围、是否 commit、回滚口径
