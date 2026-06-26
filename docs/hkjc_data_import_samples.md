# HKJC 外部数据样本导入记录

日期：2026-06-26

关联 OpenSpec change：`start-hkjc-data-import-and-global-spikes`

## 边界

- 本记录先描述本地或隔离 SQLite 数据库验证，并在后文追加生产样本 commit 记录。
- 已在生产执行一次 HKJC fixture 样本 commit；范围仅限 `stable/fixtures/hkjc/2026-06-21-race-date-sample.json`。
- 真实 HKJC 官方 HTML 入口已完成本地小范围 dry-run 和隔离 SQLite commit 验证；生产最近 2 个月全量 dry-run/commit 尚未执行。
- 本轮未把 HKJC 数据生成公开比赛页、赛果页或马匹页。
- 日本 netkeiba 外部数据导入不属于本记录。

## 样本 payload

样本保存位置：

- `server/stable/fixtures/hkjc/2026-06-21-race-date-sample.json`
- `server/stable/fixtures/hkjc/2026-06-21-race-sample.json`
- `server/stable/fixtures/hkjc/2026-06-21-horse-sample.json`

样本来源口径：

- 来源站点：HKJC
- 来源 URL：`https://racing.hkjc.com/racing/information/English/Racing/DisplaySectionalTime.aspx?RaceDate=21/06/2026&Racecourse=ST&RaceNo=6`
- 样本范围：`2026-06-21` 沙田 Race 6 的最小赛日、单场、单马 fixture，用于验证 importer 字段映射和写库边界。

## 隔离数据库

隔离数据库路径：

- `/tmp/umanews-hkjc-apply.sqlite3`

迁移命令：

```bash
DB_ENGINE=sqlite SQLITE_DB_PATH=/tmp/umanews-hkjc-apply.sqlite3 /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py migrate --noinput
```

## 执行结果

赛日 dry-run：

```bash
DB_ENGINE=sqlite SQLITE_DB_PATH=/tmp/umanews-hkjc-apply.sqlite3 /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py import_hkjc_external_data --race-date 2026-06-21 --payload-file server/stable/fixtures/hkjc/2026-06-21-race-date-sample.json
```

结果：

- `dry_run=true`
- `coverage_stats={"races": 1, "entries": 2, "results": 2, "horses": 2}`
- `would_write_formal_tables=false`

赛日 commit：

```bash
DB_ENGINE=sqlite SQLITE_DB_PATH=/tmp/umanews-hkjc-apply.sqlite3 /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py import_hkjc_external_data --race-date 2026-06-21 --payload-file server/stable/fixtures/hkjc/2026-06-21-race-date-sample.json --commit
```

结果：

- `run_id=1`
- `success_count=7`
- `coverage_stats={"races": 1, "entries": 2, "results": 2, "horses": 2}`

统计查询：

```bash
DB_ENGINE=sqlite SQLITE_DB_PATH=/tmp/umanews-hkjc-apply.sqlite3 /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py import_hkjc_external_data --stats-run-id 1
```

结果：

- `status=success`
- `success_count=7`
- `failure_count=0`
- `error_count=0`

马名索引查询：

```bash
DB_ENGINE=sqlite SQLITE_DB_PATH=/tmp/umanews-hkjc-apply.sqlite3 /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py import_hkjc_external_data --lookup-name "STELLAR EXPRESS"
```

结果：

- 命中 `external_horse_id=HKH_STELLAR_EXPRESS`
- `source_language=en`
- `confidence=100`

单场 dry-run / commit：

```bash
DB_ENGINE=sqlite SQLITE_DB_PATH=/tmp/umanews-hkjc-apply.sqlite3 /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py import_hkjc_external_data --race-id HK20260621ST06 --payload-file server/stable/fixtures/hkjc/2026-06-21-race-sample.json
DB_ENGINE=sqlite SQLITE_DB_PATH=/tmp/umanews-hkjc-apply.sqlite3 /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py import_hkjc_external_data --race-id HK20260621ST06 --payload-file server/stable/fixtures/hkjc/2026-06-21-race-sample.json --commit
```

结果：

- dry-run coverage：`{"races": 1, "entries": 1, "results": 1, "horses": 1}`
- commit `run_id=2`
- commit `success_count=3`

单马 dry-run / commit：

```bash
DB_ENGINE=sqlite SQLITE_DB_PATH=/tmp/umanews-hkjc-apply.sqlite3 /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py import_hkjc_external_data --horse-id HKH_STELLAR_EXPRESS --payload-file server/stable/fixtures/hkjc/2026-06-21-horse-sample.json
DB_ENGINE=sqlite SQLITE_DB_PATH=/tmp/umanews-hkjc-apply.sqlite3 /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py import_hkjc_external_data --horse-id HKH_STELLAR_EXPRESS --payload-file server/stable/fixtures/hkjc/2026-06-21-horse-sample.json --commit
```

结果：

- dry-run coverage：`{"races": 0, "entries": 0, "results": 0, "horses": 1}`
- commit `run_id=3`
- commit `success_count=1`

隔离库最终统计：

- `ExternalDataImportRun=3`
- `ExternalRace=1`
- `ExternalRaceEntry=2`
- `ExternalRaceResult=2`
- `ExternalHorse=2`
- `ExternalHorseAlias=4`

## 注意事项

- 曾经把单场 commit 和单马 commit 并行写入同一个临时 SQLite，触发一次 `database is locked`；改为顺序执行后单马 commit 正常通过。这是临时 SQLite 并发限制，不是生产 PostgreSQL 或 importer 逻辑问题。
- `--lookup-name STELLAR` 未命中，`--lookup-name "STELLAR EXPRESS"` 命中，说明当前 lookup 更接近规范化精确查询，不应记录为模糊搜索能力。
- 后续生产 HKJC commit 前仍必须完成数据库备份、导入锁检查、长导入窗口检查、容器健康检查和用户显式确认。

## 真实网络 dry-run 负向结论

本轮用当前最小网络 URL 构造在本地隔离数据库执行：

```bash
DB_ENGINE=sqlite SQLITE_DB_PATH=/tmp/umanews-hkjc-apply.sqlite3 /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py import_hkjc_external_data --race-date 2026-06-21 --allow-network
```

结果：

- `CommandError: HKJC network dry-run failed with HTTP 404: https://racing.hkjc.com/racing/2026-06-21`
- 未写正式表。
- 未进入 commit。

结论：当前 `HKJC_IMPORT_NETWORK_BASE_URL + /racing/<race_date>` 只是安全占位 dry-run 路径，不代表已确认 HKJC 稳定 JSON/API。后续如要真实网络导入，必须先单独定位 HKJC 公开 JSON/API、页面脚本 payload 或 HTML 解析入口，再扩展 importer 的网络适配层。

## 生产上线前导入锁检查

2026-06-26 上线前只读检查生产：

- 生产 HEAD：`4d09d25`
- `ExternalDataImportLock` 运行中锁：无
- `ExternalDataImportRun(status="started")`：无
- `web` 容器：healthy

上线阶段未执行生产 HKJC 样本 commit；生产样本写入在后续用户明确确认后单独执行，记录如下。

## 生产样本 commit

2026-06-26 用户确认“开始跑”后，在生产 `/opt/umanewsbot` 执行一次 HKJC fixture 样本写入。

执行范围：

- payload：`stable/fixtures/hkjc/2026-06-21-race-date-sample.json`
- target：`race_date=2026-06-21`
- 数据来源：仓库 fixture，不是 HKJC 真实网络请求
- 前台影响：不创建公开比赛页、赛果页或马匹页

执行前备份：

- 备份文件：`backups/db/pre-hkjc-sample-20260626_180646.sql.gz`
- 大小：`42M`
- `gzip -t`：通过

生产 dry-run：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py import_hkjc_external_data --race-date 2026-06-21 --payload-file stable/fixtures/hkjc/2026-06-21-race-date-sample.json
```

结果：

- `dry_run=true`
- `coverage_stats={"races": 1, "entries": 2, "results": 2, "horses": 2}`
- `would_write_formal_tables=false`

生产 commit：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py import_hkjc_external_data --race-date 2026-06-21 --payload-file stable/fixtures/hkjc/2026-06-21-race-date-sample.json --commit
```

结果：

- `run_id=1960`
- `status=success`
- `success_count=7`
- `skipped_count=0`
- `failure_count=0`
- `coverage_stats={"races": 1, "entries": 2, "results": 2, "horses": 2}`

提交后统计：

- `ExternalDataImportRun(source="hkjc")=1`
- `ExternalRace(source="hkjc")=1`
- `ExternalRaceEntry(source="hkjc")=2`
- `ExternalRaceResult(source="hkjc")=2`
- `ExternalHorse(source="hkjc")=2`
- `ExternalHorseAlias(source="hkjc")=4`
- `--lookup-name "STELLAR EXPRESS"` 命中 `HKH_STELLAR_EXPRESS`，`confidence=100`

提交后运行态：

- HKJC 锁记录存在但未占用：`locked_by_run_id=None`，`acquired_at=None`
- 未发现仍在运行的 `import_hkjc_external_data` 进程
- `http://umafans.run/healthz/` 返回 `200`

## 真实 HKJC HTML 单场验证

2026-06-26 在新 change `connect-real-global-racing-databases` 下，已将 HKJC 官方 HTML 单场结果页接入本地 parser 和 importer 小样本链路。

真实入口：

- 单场结果：`https://racing.hkjc.com/en-us/local/information/localresults?racedate=2026/06/24&Racecourse=HV&RaceNo=1`
- 马匹详情样例：`https://racing.hkjc.com/en-us/local/information/horse?horseid=HK_2023_J524`

本地真实 dry-run：

```bash
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py import_hkjc_external_data --race-id HK20260624HV01 --allow-network
```

结果：

- 请求数：`1`
- HTTP 状态：`200`
- `coverage_stats={"races": 1, "entries": 12, "results": 12, "horses": 12}`
- `completion={"is_complete": false, "stop_reason": "limit_horses_reached", "meetings_found": 28, "races_imported": 1, "unique_horses_found": 12, "horse_profiles_fetched": 1, "limit_races": 1, "limit_horses": 1, "max_requests": 10}`
- `would_write_formal_tables=false`

隔离 SQLite 真实 commit：

```bash
rm -f /tmp/umanews-hkjc-real-single.sqlite3
DB_ENGINE=sqlite SQLITE_DB_PATH=/tmp/umanews-hkjc-real-single.sqlite3 /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py migrate --noinput
DB_ENGINE=sqlite SQLITE_DB_PATH=/tmp/umanews-hkjc-real-single.sqlite3 CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py import_hkjc_external_data --race-id HK20260624HV01 --allow-network --commit
```

结果：

- `run_id=1`
- `status=success`
- `success_count=25`
- `failure_count=0`
- `coverage_stats={"races": 1, "entries": 12, "results": 12, "horses": 12}`
- 隔离库计数：`ExternalRace=1`、`ExternalRaceEntry=12`、`ExternalRaceResult=12`、`ExternalHorseAlias=12`

边界：

- 本验证只覆盖真实单场结果 HTML；尚未覆盖最近 2 个月批量赛日、所有 race links 聚合或马匹详情补抓。
- 本验证没有写生产数据库。
- 生产 HKJC 真实网络 commit 前仍必须先完成最近 2 个月 dry-run、数据库备份、锁检查、用户确认和运行手册记录。

## 真实 HKJC recent-days 小范围验证

2026-06-26 在 `connect-real-global-racing-databases` 下，已将 HKJC `recent-days/date-range` 小范围真实链路接入本地 importer：赛日列表 -> 赛日页 race links -> 单场结果 -> 涉及马匹详情 profile。

本地真实 dry-run：

```bash
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true HKJC_IMPORT_REQUEST_INTERVAL_SECONDS=1 HKJC_IMPORT_MAX_REQUESTS_PER_RUN=10 /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py import_hkjc_external_data --recent-days 60 --end-date 2026-06-26 --limit-races 1 --limit-horses 1 --max-requests 10 --allow-network
```

结果：

- 请求数：`4`
- 请求入口：
  - `https://racing.hkjc.com/en-us/local/information/localresults`
  - `https://racing.hkjc.com/en-us/local/information/localresults?racedate=2026/06/24`
  - `https://racing.hkjc.com/en-us/local/information/localresults?racedate=2026/06/24&Racecourse=HV&RaceNo=2`
  - `https://racing.hkjc.com/en-us/local/information/horse?horseid=HK_2022_H293`
- `coverage_stats={"races": 1, "entries": 12, "results": 12, "horses": 12}`
- `would_write_formal_tables=false`

隔离 SQLite 真实 commit：

```bash
rm -f /tmp/umanews-hkjc-real-range.sqlite3
DB_ENGINE=sqlite SQLITE_DB_PATH=/tmp/umanews-hkjc-real-range.sqlite3 /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py migrate --noinput
DB_ENGINE=sqlite SQLITE_DB_PATH=/tmp/umanews-hkjc-real-range.sqlite3 CELERY_TASK_ALWAYS_EAGER=true HKJC_IMPORT_REQUEST_INTERVAL_SECONDS=1 HKJC_IMPORT_MAX_REQUESTS_PER_RUN=10 /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py import_hkjc_external_data --recent-days 60 --end-date 2026-06-26 --limit-races 1 --limit-horses 1 --max-requests 10 --allow-network --commit
```

结果：

- 首次 `run_id=1`，重复执行 `run_id=2`
- 每次 `success_count=26`
- `coverage_stats={"races": 1, "entries": 12, "results": 12, "horses": 12}`
- `completion.is_complete=false`，`stop_reason=limit_horses_reached`
- 首次 commit 后计数：`ExternalRace=1`、`ExternalRaceEntry=12`、`ExternalRaceResult=12`、`ExternalHorse=1`、`ExternalHorseAlias=12`
- 解析到的马匹详情样例：`HK_2022_H293` / `ALL ARE MINE` / `GER` / `Gelding` / `B Crawford`
- 重复 commit 后正式对象计数保持：`ExternalRace=1`、`ExternalRaceEntry=12`、`ExternalRaceResult=12`、`ExternalHorse=1`、`ExternalHorseAlias=12`
- HKJC 单来源锁已释放：`locked_by_run_id=None`

边界：

- 本验证只抓取 `limit-races=1` 和 `limit-horses=1`，尚未覆盖生产最近 2 个月全量。
- `coverage_stats.horses=12` 表示单场 entries/results 涉及 12 匹唯一马；本次因 `limit-horses=1` 只补抓其中 1 匹 profile。
- `completion.is_complete=false` 明确表示这是样本链路验证，不能作为最近 2 个月全量完成证明。
- 生产全量 commit 前仍必须执行生产备份、锁检查、健康检查、最近 2 个月 dry-run，并取得用户显式确认。
