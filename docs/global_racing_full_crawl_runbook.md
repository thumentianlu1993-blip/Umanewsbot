# 全球赛马数据库完整爬取运行手册

日期：2026-06-27

适用范围：香港 HKJC、英国 Sporting Life、法国 Geny、美国 Horse Racing Nation 最近 2 个月赛事与涉及马匹详情的后续完整抓取会话。

本手册是执行 runbook，不是完成记录。当前状态仍以 `docs/global_racing_full_crawl_completion_audit.md` 为准：四地真实接入 proof 已成立，但最近 2 个月完整大量爬取和英法美生产真实网络 commit 尚未完成。

## 执行原则

- 每个地区先 `plan-only`，再按 plan 输出的小批次执行 dry-run。
- dry-run 全部完成且汇总无缺口后，才讨论生产 `--commit`。
- 默认命令不得写库；只有用户显式确认后才能添加 `--commit`。
- 每个地区的 plan/dry-run 输出必须保存到独立输入目录，例如 `runtime/global_racing_import/uk/`；文件名包含地区、批次、日期和 `plan` / `dryrun` / `commit`。
- 审计输出不要写入被审计的输入目录，避免下一次审计把上一次 audit JSON 当成 batch JSON 重新读取。
- 任何 `completion.is_complete=false`、`stop_reason=rate_limited`、请求超时、输出空文件或锁未释放，都不得进入 commit；当前代码也会在 `--commit` 前拒绝这类 partial payload。
- 不加入 Celery Beat，不创建前台比赛页、赛果页或马匹页，不触发 QQ 推送。

## 生产预检

```bash
cd /opt/umanewsbot
git rev-parse --short HEAD
docker compose -f docker-compose.prod.lowcost.yml ps
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py check
curl -sS -o /dev/null -w "local_healthz=%{http_code}\n" http://127.0.0.1/healthz/
curl -sS -o /dev/null -w "public_healthz=%{http_code}\n" http://umafans.run/healthz/
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py shell -c "from stable.models import ExternalDataImportRun, ExternalDataImportLock; print('started_runs', ExternalDataImportRun.objects.filter(status='started').count()); print(list(ExternalDataImportLock.objects.values('source','racing_region','locked_by_run_id','acquired_at')))"
```

进入 commit 前必须备份：

```bash
cd /opt/umanewsbot
mkdir -p backups/db
backup_path="backups/db/pre-global-racing-full-crawl-$(date +%Y%m%d_%H%M%S).sql.gz"
docker compose -f docker-compose.prod.lowcost.yml exec -T db pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" | gzip > "$backup_path"
gzip -t "$backup_path"
echo "$backup_path"
```

## 批次台账模板

每个地区维护一段台账，至少记录：

```text
region:
source:
window:
plan_file:
plan_total_races:
plan_batches:
batch_id:
command:
output_file:
request_count:
coverage_stats:
completion:
horse_profiles_fetched:
failure_summary:
would_write_formal_tables:
commit_run_id:
table_counts_after:
lock_after:
healthz_after:
operator_decision:
```

每个地区的 dry-run JSON 批次输出落盘后，先运行离线审计命令。该命令只读 JSON，不发网络请求、不写数据库；plan-only 文件会计入计划文件数量，但 coverage 汇总只统计非 plan 的 dry-run 批次：

```bash
docker compose -f docker-compose.prod.lowcost.yml run --rm --no-deps \
  web python manage.py audit_global_racing_import_outputs \
  --input-dir runtime/global_racing_import/uk \
  --pattern "*.json" \
  --fail-on-incomplete \
  | tee runtime/global_racing_import/uk-audit-YYYYMMDD.json
```

只有输出中的 `commit_candidate_ready=true`、`blocking_reasons=[]`、`source_count=1`、`missing_source_file_count=0`、`plan_file_count>=1`、`batch_file_count>=1`、`planned_item_count>=1`、`incomplete_plan_file_count=0`、`non_dry_run_plan_file_count=0`、`limited_plan_file_count=0`、`incomplete_horse_detail_file_count=0`、`duplicate_planned_item_count=0`、`duplicate_covered_item_count=0`、`would_write_formal_table_file_count=0`、`missing_planned_item_count=0`、`extra_covered_item_count=0`，且人工复核 coverage 与 plan 批次一致后，才允许进入备份、锁检查和用户显式确认步骤。若命令报 `incomplete global racing import outputs`，或 JSON 中的 `blocking_reasons` 包含 `missing source ...`、`mixed sources ...`、`missing plan file`、`missing batch file`、`empty plan items`、`incomplete plan ...`、`non-dry-run plan ...`、`limited plan ...`、`incomplete horse details ...`、`duplicate planned ...`、`duplicate covered ...`、`would write formal tables ...`、`missing planned ...` 或 `extra covered ...`，必须先补跑或排查对应批次，不得添加 `--commit`。plan 覆盖比对会优先使用 `race_ids`，并在缺少 race IDs 时兜底使用 `partants_urls` 或 `race_urls`。

从 plan-only JSON 执行具体批次前，先用只读渲染命令生成精确批次命令，避免手工复制 URL/ID 时跑错批次。该命令只读 plan 文件，不发网络请求、不写数据库：

```bash
python server/manage.py render_global_racing_batch_command \
  --plan-file runtime/global_racing_import/<region>/<plan-file>.json \
  --batch N \
  --output-dir runtime/global_racing_import/<region> \
  --limit-horses M
```

如要先生成完整批次清单，用：

```bash
python server/manage.py render_global_racing_batch_command \
  --plan-file runtime/global_racing_import/<region>/<plan-file>.json \
  --all-batches \
  --output-dir runtime/global_racing_import/<region> \
  --limit-horses M
```

检查输出中的 `source`、`batch_number`、`target_key`、`target_count`、`suggested_output_file`、`suggested_output_path`、`command_line` 和 `tee_command_line` 后，再在生产容器中按 `tee_command_line` 逐批执行 dry-run，并按 `suggested_output_path` 写到该地区目录。渲染规则为：HKJC/HRN 使用 `race_ids`，Sporting Life 使用 `race_urls`，Geny 使用 `partants_urls`；渲染结果默认只生成 dry-run 命令，只有显式传 `--commit` 才会包含 `--commit`。建议输出名形如 `uk-batch-001-dryrun.json`、`france-geny-batch-002-dryrun.json`，用于避免覆盖或混放批次 JSON。`--output-dir` 只参与渲染建议路径，不会创建目录或写文件；未提供 `--output-dir` 时不会输出 `tee_command_line`。

渲染结果会带 `artifact_type=global_racing_batch_command(s)`，离线审计会识别并忽略这类只读 artifact；但为保持目录清晰，仍建议把命令清单保存为 `*-commands.json`，不要命名成 `*-plan.json` 或 `*-batch-*.json`。

少量真实 proof 输出使用同一命令的 `--proof-only` 模式审计。该模式只证明入口和 parser 可用，不证明完整两个月覆盖，也不允许进入生产 commit 候选：

```bash
docker compose -f docker-compose.prod.lowcost.yml run --rm --no-deps \
  web python manage.py audit_global_racing_import_outputs \
  --input-dir runtime/global_racing_import/proof-YYYYMMDD \
  --pattern "*/*.json" \
  --proof-only \
  --expected-sources sporting_life,geny_france,horse_racing_nation \
  --expected-request-types 'sporting_life:race|horse,geny_france:partants|results|horse,horse_racing_nation:track_day|horse' \
  --fail-on-incomplete \
  | tee runtime/global_racing_import/proof-YYYYMMDD-audit.json
```

proof-only 通过时应看到 `handoff_decision=proof_only_ready_not_commit_candidate`、`handoff_decision_reasons` 包含 `proof-only audit passed` / `commit audit still blocked` / `complete 60-day crawl and commit gate remain required`、`proof_ready=true`、`proof_blocking_reasons=[]`、`missing_expected_sources=[]`、`missing_proof_request_types=[]`、`proof_file_count>=1`、`proof_request_count>=1`、`proof_successful_response_count == proof_request_count`，同时仍允许 `commit_candidate_ready=false`。人工复核时还应查看 `audit_parameters`，确认输入目录、pattern、proof-only、fail-on-incomplete、期望来源和期望请求类型与本轮交接意图一致；再查看 `proof_sources`，确认每个来源都有独立的 `files`、`file_count`、`complete_file_count`、`incomplete_file_count`、`stop_reasons`、`request_count`、`successful_response_count`、`coverage_totals` 和 `request_types`，并能从 `files` 回到原始 proof JSON。少量 proof 通常应显示 `incomplete_file_count>0` 且 `stop_reasons` 为受控限量原因；这不能作为完整 commit 候选。若出现 `plan-only proof ...`、`empty proof requests ...`、`non-success proof response ...`、`empty proof coverage ...`、`disallowed proof stop ...`、`missing source ...`、`missing expected proof source ...`、`missing proof request type ...` 或 `would write formal tables ...`，该 proof 不能作为接入可用证据。

## 香港 HKJC

当前正式进度：生产已完成前 `120/144` 场 full dry-run，未 commit。停点后的 `hkjc-batch7a/7b` 文件不作为正式进度依据。

下一轮先重跑最新 plan：

```bash
mkdir -p runtime/global_racing_import/hkjc
docker compose -f docker-compose.prod.lowcost.yml run --rm --no-deps \
  -e HKJC_IMPORT_REQUEST_INTERVAL_SECONDS=8 \
  -e HKJC_IMPORT_MAX_REQUESTS_PER_RUN=120 \
  web python manage.py import_hkjc_external_data \
  --recent-days 60 \
  --end-date YYYY-MM-DD \
  --plan-only \
  --limit-races 20 \
  --max-requests 120 \
  --allow-network \
  | tee runtime/global_racing_import/hkjc/hkjc-plan-YYYYMMDD.json
```

若最新 plan 仍可确认前 `120` 场已作为正式进度接受，先用 `render_global_racing_batch_command --plan-file ... --batch N` 渲染停点后的精确 `race_ids` 批次，再执行返回的 dry-run 命令。否则按最新 plan 重新切批：

```bash
docker compose -f docker-compose.prod.lowcost.yml run --rm --no-deps \
  -e HKJC_IMPORT_REQUEST_INTERVAL_SECONDS=8 \
  -e HKJC_IMPORT_MAX_REQUESTS_PER_RUN=240 \
  web python manage.py import_hkjc_external_data \
  --recent-days 60 \
  --end-date YYYY-MM-DD \
  --skip-races 120 \
  --limit-races 5 \
  --limit-horses 999 \
  --max-requests 240 \
  --allow-network \
  | tee runtime/global_racing_import/hkjc/hkjc-batch-N-dryrun-YYYYMMDD.json
```

HKJC commit 前必须逐批确认：

- `completion.is_complete=true`
- 覆盖 race 数与 plan 剩余批次一致
- `horse_profiles_fetched` 覆盖本批唯一马匹，或 HKJC 返回中有等价马匹详情字段
- 生产备份、锁检查、健康检查和用户显式确认齐全

## 英国 Sporting Life

当前 proof：过滤后英国赛场最近 60 天 plan 为 `35` 场、`7` 批，racecard dry-run 覆盖 `35/35`；两组精确批次已证明全量 profile 闭环可用，但尚未补齐全部 `35` 场涉及马匹 profile，也未生产 commit。

先生成最新过滤后 plan：

```bash
mkdir -p runtime/global_racing_import/uk
docker compose -f docker-compose.prod.lowcost.yml run --rm --no-deps \
  -e UK_IMPORT_REQUEST_INTERVAL_SECONDS=2 \
  -e UK_IMPORT_MAX_REQUESTS_PER_RUN=160 \
  web python manage.py import_uk_external_data \
  --recent-days 60 \
  --end-date YYYY-MM-DD \
  --plan-only \
  --batch-size 5 \
  --allow-network \
  | tee runtime/global_racing_import/uk/uk-plan-YYYYMMDD.json
```

再用 `render_global_racing_batch_command --plan-file runtime/global_racing_import/uk/uk-plan-YYYYMMDD.json --batch N` 从 plan 输出的 `race_urls` 渲染精确 dry-run 命令。完整 profile 批次不要设置过小的 `--limit-horses`，或设置为不小于本批唯一马匹数：

```bash
docker compose -f docker-compose.prod.lowcost.yml run --rm --no-deps \
  -e UK_IMPORT_REQUEST_INTERVAL_SECONDS=2 \
  -e UK_IMPORT_MAX_REQUESTS_PER_RUN=240 \
  web python manage.py import_uk_external_data \
  --race-urls URL1,URL2,URL3,URL4,URL5 \
  --allow-network \
  | tee runtime/global_racing_import/uk/uk-batch-N-dryrun-YYYYMMDD.json
```

英国 commit 前必须逐批确认：

- plan 只包含英国赛场 allowlist 命中的 `race_urls`
- 所有 plan 批次均 `completion.is_complete=true`
- 所有涉及马匹 profile 均已补抓，不能只用 racecard 覆盖替代
- 本地 `--race-urls --commit` 测试只能证明命令能力，不能替代生产真实网络 commit 门禁

## 法国 Geny

当前 proof：France Galop 仅证明当日官方入口；最近 2 个月历史窗口以 Geny 为主。Geny 小批 dry-run 和独立 profile proof 已通过，但完整 60 天 plan 和所有 profile 未完成。

先生成 Geny 最新 plan：

```bash
mkdir -p runtime/global_racing_import/france-geny
docker compose -f docker-compose.prod.lowcost.yml run --rm --no-deps \
  -e FRANCE_IMPORT_REQUEST_INTERVAL_SECONDS=10 \
  -e FRANCE_IMPORT_MAX_REQUESTS_PER_RUN=120 \
  web python manage.py import_france_external_data \
  --source geny \
  --recent-days 60 \
  --end-date YYYY-MM-DD \
  --plan-only \
  --batch-size 5 \
  --allow-network \
  | tee runtime/global_racing_import/france-geny/france-geny-plan-YYYYMMDD.json
```

再用 `render_global_racing_batch_command --plan-file runtime/global_racing_import/france-geny/france-geny-plan-YYYYMMDD.json --batch N` 从 plan 输出的 `partants_urls` 低频渲染精确 dry-run 命令。需要独立 profile 时显式设置 `--limit-horses`，并让它覆盖本批唯一马匹数：

```bash
docker compose -f docker-compose.prod.lowcost.yml run --rm --no-deps \
  -e FRANCE_IMPORT_REQUEST_INTERVAL_SECONDS=10 \
  -e FRANCE_IMPORT_MAX_REQUESTS_PER_RUN=240 \
  web python manage.py import_france_external_data \
  --source geny \
  --partants-urls URL1,URL2,URL3,URL4,URL5 \
  --limit-horses M \
  --allow-network \
  | tee runtime/global_racing_import/france-geny/france-geny-batch-N-dryrun-YYYYMMDD.json
```

法国 commit 前必须逐批确认：

- 没有 `429`、登录跳转或 partial dry-run
- `partants -> results -> horse profile` 请求证据完整
- 若使用行内详情替代独立 profile，文档必须明确来源限制和字段覆盖
- 本地 `--partants-urls --commit` 测试只能证明命令能力，不能替代生产真实网络 commit 门禁

## 美国 Horse Racing Nation

当前 proof：Equibase 返回防护页，DRF 是 JS 应用壳；第一版以 HRN 为主。HRN 日期窗口、track-day、runner/result table 和 profile proof 已通过，但完整 60 天日期/赛场覆盖尚未完成。`--limit-tracks` 只能用于 proof 或探索，不得用于后续完整爬取的 commit 候选 plan；带覆盖限制的 plan 会被离线审计标记为 `limited plan ...`。

先生成 HRN 最新 plan：

```bash
mkdir -p runtime/global_racing_import/us-hrn
docker compose -f docker-compose.prod.lowcost.yml run --rm --no-deps \
  -e US_IMPORT_REQUEST_INTERVAL_SECONDS=5 \
  -e US_IMPORT_MAX_REQUESTS_PER_RUN=240 \
  web python manage.py import_us_external_data \
  --recent-days 60 \
  --end-date YYYY-MM-DD \
  --seed-track churchill-downs \
  --plan-only \
  --batch-size 5 \
  --allow-network \
  | tee runtime/global_racing_import/us-hrn/us-hrn-plan-YYYYMMDD.json
```

再用 `render_global_racing_batch_command --plan-file runtime/global_racing_import/us-hrn/us-hrn-plan-YYYYMMDD.json --batch N` 从 plan 输出的 `race_ids` 渲染精确 dry-run 命令。需要独立 profile 时显式设置 `--limit-horses`，并让它覆盖本批唯一马匹数：

```bash
docker compose -f docker-compose.prod.lowcost.yml run --rm --no-deps \
  -e US_IMPORT_REQUEST_INTERVAL_SECONDS=5 \
  -e US_IMPORT_MAX_REQUESTS_PER_RUN=240 \
  web python manage.py import_us_external_data \
  --race-ids HRN_track_YYYY-MM-DD_N,HRN_track_YYYY-MM-DD_N \
  --limit-horses M \
  --allow-network \
  | tee runtime/global_racing_import/us-hrn/us-hrn-batch-N-dryrun-YYYYMMDD.json
```

美国 commit 前必须逐批确认：

- plan 对日期范围和赛场覆盖口径有记录，不能只覆盖单个 seed track，也不能带 `limit_tracks` 等覆盖限制
- `track_days_found`、`track_days_fetched`、`race_ids_selected` 与 plan 批次一致
- 所有涉及马匹 profile 已补抓，或文档明确 HRN 当批字段限制
- 本地 `--race-ids --commit` 测试只能证明命令能力，不能替代生产真实网络 commit 门禁

## 完成判定

四地完整目标只有在以下证据都存在时才能标记完成：

- 每地最新 plan-only 输出已归档，并且 plan 总量、批次数和执行批次一一对应，不存在重复计划项或重复覆盖项。
- 每地已运行 `audit_global_racing_import_outputs --fail-on-incomplete` 并保存审计输出，且 `commit_candidate_ready=true`、`blocking_reasons=[]`、`source_count=1`、`missing_source_file_count=0`、`plan_file_count>=1`、`batch_file_count>=1`、`planned_item_count>=1`、`incomplete_plan_file_count=0`、`non_dry_run_plan_file_count=0`、`limited_plan_file_count=0`、`incomplete_horse_detail_file_count=0`、`duplicate_planned_item_count=0`、`duplicate_covered_item_count=0`、`would_write_formal_table_file_count=0`、`missing_planned_item_count=0`、`extra_covered_item_count=0`。
- 每个 dry-run 批次 `completion.is_complete=true`。
- 每地所有比赛、entries、results、唯一马匹和 profile 或等价行内详情覆盖都有汇总数字。
- 任何失败、限流、超时、空输出或跳转登录都有处理结论，且未进入 commit。
- 如写生产库，每地都有备份路径、commit 命令、`run_id`、表计数、锁释放、健康检查和用户显式确认。
- `docs/current_state.md`、`docs/project_status.md`、`docs/deploy_runbook.md` 和 `docs/global_racing_full_crawl_completion_audit.md` 已更新为完成记录。
