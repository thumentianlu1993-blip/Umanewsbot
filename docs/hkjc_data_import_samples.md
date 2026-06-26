# HKJC 外部数据样本导入记录

日期：2026-06-26

关联 OpenSpec change：`start-hkjc-data-import-and-global-spikes`

## 边界

- 本记录先描述本地或隔离 SQLite 数据库验证，并在后文追加生产样本 commit 记录。
- 已在生产执行一次 HKJC fixture 样本 commit；范围仅限 `stable/fixtures/hkjc/2026-06-21-race-date-sample.json`。
- 真实 HKJC 网络抓取尚未开始，当前 `--allow-network` 仍只是入口探测，不代表稳定数据源已确认。
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
