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

## 真实 HKJC recent-days plan-only 批次计划

2026-06-26 追加 `--plan-only` 预检能力，用于生产全量前低风险估算赛日和比赛数量。该模式只请求赛日列表和每个赛日的 race links，不请求单场结果页或马匹详情页，不写正式表。

命令：

```bash
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true HKJC_IMPORT_REQUEST_INTERVAL_SECONDS=1 HKJC_IMPORT_MAX_REQUESTS_PER_RUN=80 /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py import_hkjc_external_data --recent-days 60 --end-date 2026-06-26 --limit-races 20 --max-requests 80 --allow-network --plan-only
```

结果：

- `plan_only=true`
- 请求数：`29` 个页面，包括 `1` 个 meeting list 和 `28` 个赛日页
- `coverage_stats={"meetings": 28, "races": 144, "estimated_requests_without_horses": 173}`
- 已过滤 HKJC overseas simulcast：`S1/S2/S3/S4/S5` 等 racecourse 不进入本地香港批次
- 本地香港 `HV/ST` 比赛共 `144` 场
- 按 `limit-races=20` 生成 `8` 批：前 7 批各 `20` 场，最后 1 批 `4` 场
- 每个 batch 带 `race_ids` 和 `skip_races`；生产执行优先使用 `--race-ids` 精确批次，避免为续批重复扫描前置赛日页，`--skip-races` 保留为日期范围续跑备选

批次续跑 smoke：

```bash
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true HKJC_IMPORT_REQUEST_INTERVAL_SECONDS=1 HKJC_IMPORT_MAX_REQUESTS_PER_RUN=80 /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py import_hkjc_external_data --recent-days 60 --end-date 2026-06-26 --skip-races 20 --limit-races 1 --limit-horses 0 --max-requests 80 --allow-network
```

结果：

- `skip_races=20`
- 实际抓取 race：`HK20260613ST04`
- `coverage_stats={"races": 1, "entries": 14, "results": 14, "horses": 14}`
- `completion.is_complete=false`
- `horse_profiles_fetched=0`，因为本次 smoke 使用 `--limit-horses 0`

精确 race-id 批次 smoke：

```bash
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true HKJC_IMPORT_REQUEST_INTERVAL_SECONDS=1 HKJC_IMPORT_MAX_REQUESTS_PER_RUN=20 /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py import_hkjc_external_data --race-ids HK20260624HV02,HK20260613ST04 --limit-horses 1 --max-requests 20 --allow-network
```

结果：

- `target_type="race_batch"`
- 请求数：`3`，顺序为 `race`、`race`、`horse`
- `coverage_stats={"races": 2, "entries": 26, "results": 26, "horses": 26}`
- `completion.is_complete=false`
- `stop_reason=limit_horses_reached`
- `horse_profiles_fetched=1`，因为本次 smoke 使用 `--limit-horses 1`
- 未写正式表，`would_write_formal_tables=false`

边界：

- plan-only 里的 `meetings=28` 是 HKJC 下拉中的目标日期页数量，其中包含会跳转到海外转播结果页的日期；正式香港本地导入以 `HV/ST` race links 为准。
- plan-only 只估算比赛批次，不知道每批最终唯一马匹数量；每批正式 commit 前仍要先执行同参数 dry-run，确认 `completion`、请求量、唯一马匹数量和失败摘要。
- `--race-ids` 适合使用 plan-only 输出的批次清单执行生产 dry-run/commit；该模式不接受 `--payload-file`、`--limit-races` 或 `--skip-races`，并且必须显式带 `--allow-network`。

## 生产 HKJC 真实网络部署与第 1 批 dry-run 中断

2026-06-26 已将 `connect-real-global-racing-databases` 当前实现部署到生产 `65d41eb`，部署前备份：

- `backups/db/pre-hkjc-real-network-20260626_202442.sql.gz`
- 大小约 `42M`
- `gzip -t` 校验通过

部署后验证：

- `manage.py check`：通过
- `http://127.0.0.1/healthz/`：`200`
- `http://umafans.run/healthz/`：`200`
- HKJC `--race-ids HK20260624HV02,HK20260613ST04 --limit-horses 1` 生产 dry-run：请求 `3` 次，解析 `2` 场、`26` entries、`26` results、`26` unique horses，未写正式表

生产 plan-only：

- `coverage_stats={"meetings": 28, "races": 144, "estimated_requests_without_horses": 173}`
- 仍为 `8` 批：前 7 批各 `20` 场，第 8 批 `4` 场

第 1 批 full dry-run：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec -T web env HKJC_IMPORT_REQUEST_INTERVAL_SECONDS=3 HKJC_IMPORT_MAX_REQUESTS_PER_RUN=400 python manage.py import_hkjc_external_data --race-ids "<batch-1-race-ids>" --max-requests 400 --allow-network
```

结果：

- 在马匹 profile 补抓阶段遇到 HKJC `ReadTimeout` / TLS handshake timeout，命令退出。
- 该运行是 dry-run，未执行 `--commit`，未写正式表。
- 中断后生产检查：HKJC 锁为空、`started_runs=0`、HKJC 表计数仍为 fixture 样本 `ExternalRace=1`、`ExternalRaceEntry=2`、`ExternalRaceResult=2`、`ExternalHorse=2`、`ExternalHorseAlias=4`。
- 已按 TDD 补充 client transient timeout retry：单个请求最多 `3` 次，失败尝试会进入请求证据；普通一次成功请求的证据格式保持兼容。

retry 补丁部署：

- 生产已从 `65d41eb` 快进到 `04c0444`
- `manage.py check`：通过
- `http://127.0.0.1/healthz/`：`200`
- `http://umafans.run/healthz/`：`200`

原第 1 批 20 场改为 4 个 5 场小批次重新 dry-run：

| 批次 | race_count | entries | results | unique horses | horse profiles | requests | retry attempts | completion |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1a | 5 | 60 | 60 | 60 | 60 | 65 | 0 | complete |
| 1b | 5 | 65 | 65 | 65 | 65 | 70 | 0 | complete |
| 1c | 5 | 65 | 65 | 65 | 65 | 70 | 0 | complete |
| 1d | 5 | 66 | 66 | 66 | 66 | 71 | 0 | complete |
| 2a | 5 | 62 | 62 | 62 | 62 | 67 | 0 | complete |
| 2b | 5 | 64 | 64 | 64 | 64 | 69 | 0 | complete |
| 2c | 5 | 61 | 61 | 61 | 61 | 66 | 0 | complete |
| 2d | 5 | 68 | 68 | 68 | 68 | 73 | 0 | complete |
| 3a | 5 | 64 | 64 | 64 | 64 | 69 | 0 | complete |
| 3b | 5 | 62 | 62 | 62 | 62 | 67 | 0 | complete |
| 3c | 5 | 61 | 61 | 61 | 61 | 66 | 0 | complete |
| 3d | 5 | 65 | 65 | 65 | 65 | 70 | 0 | complete |
| 4a | 5 | 65 | 65 | 65 | 65 | 70 | 0 | complete |
| 4b | 5 | 58 | 58 | 58 | 58 | 63 | 0 | complete |
| 4c | 5 | 66 | 66 | 66 | 66 | 71 | 0 | complete |
| 4d | 5 | 63 | 63 | 63 | 63 | 68 | 0 | complete |
| 5a | 5 | 67 | 67 | 67 | 67 | 73 | 2 | complete |
| 5b | 5 | 60 | 60 | 60 | 60 | 65 | 0 | complete |
| 5c | 5 | 62 | 62 | 62 | 62 | 67 | 0 | complete |
| 5d | 5 | 70 | 70 | 70 | 70 | 75 | 0 | complete |
| 6a | 5 | 56 | 56 | 56 | 56 | 61 | 0 | complete |
| 6b | 5 | 61 | 61 | 61 | 61 | 66 | 0 | complete |
| 6c | 5 | 66 | 66 | 66 | 66 | 71 | 0 | complete |
| 6d | 5 | 65 | 65 | 65 | 65 | 70 | 0 | complete |

小批次 dry-run 输出保存在生产：

- `runtime/hkjc_import/hkjc-batch1a-dryrun-20260626.json`
- `runtime/hkjc_import/hkjc-batch1b-dryrun-20260626.json`
- `runtime/hkjc_import/hkjc-batch1c-dryrun-20260626.json`
- `runtime/hkjc_import/hkjc-batch1d-dryrun-20260626.json`
- `runtime/hkjc_import/hkjc-batch2a-dryrun-20260626.json`
- `runtime/hkjc_import/hkjc-batch2b-dryrun-20260626.json`
- `runtime/hkjc_import/hkjc-batch2c-dryrun-20260626.json`
- `runtime/hkjc_import/hkjc-batch2d-dryrun-20260626.json`
- `runtime/hkjc_import/hkjc-batch3a-dryrun-20260626.json`
- `runtime/hkjc_import/hkjc-batch3b-dryrun-20260626.json`
- `runtime/hkjc_import/hkjc-batch3c-dryrun-20260626.json`
- `runtime/hkjc_import/hkjc-batch3d-dryrun-20260626.json`
- `runtime/hkjc_import/hkjc-batch4a-dryrun-20260626.json`
- `runtime/hkjc_import/hkjc-batch4b-dryrun-20260626.json`
- `runtime/hkjc_import/hkjc-batch4c-dryrun-20260626.json`
- `runtime/hkjc_import/hkjc-batch4d-dryrun-20260626.json`
- `runtime/hkjc_import/hkjc-batch5a-dryrun-20260626.json`
- `runtime/hkjc_import/hkjc-batch5b-dryrun-20260626.json`
- `runtime/hkjc_import/hkjc-batch5c-dryrun-20260626.json`
- `runtime/hkjc_import/hkjc-batch5d-dryrun-20260626.json`
- `runtime/hkjc_import/hkjc-batch6a-dryrun-20260626.json`
- `runtime/hkjc_import/hkjc-batch6b-dryrun-20260626.json`
- `runtime/hkjc_import/hkjc-batch6c-dryrun-20260626.json`
- `runtime/hkjc_import/hkjc-batch6d-dryrun-20260626.json`

dry-run 后生产复查：

- `started_runs=0`
- HKJC `ExternalDataImportLock.locked_by_run_id=None`
- HKJC 正式表计数仍为上次 fixture 样本：`ExternalRace=1`、`ExternalRaceEntry=2`、`ExternalRaceResult=2`、`ExternalHorse=2`、`ExternalHorseAlias=4`
- 当前已完成前 6 个 plan-only 批次共 `120` 场 full dry-run，均未执行 `--commit`
- 3c 首次执行时遇到一次执行容器 `137` 中断，输出文件为 `0` 字节；复查服务、锁和表计数均安全。随后改用一次性 `docker compose run --rm --no-deps web ...` 容器重跑 3c/3d 并完成，避免长 dry-run 进入常驻 `web` 容器。
