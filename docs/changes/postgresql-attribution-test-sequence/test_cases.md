# PostgreSQL 归属测试序列测试用例

## 测试环境

- 工作目录：
  `/Users/mentianlu/Code/umanews/.worktrees/add-new-region-news-sources-release-candidate`
- 应用镜像：`umanews-five-region-rereview:local`
- 数据库镜像：`postgres:16-alpine`
- 隔离网络：`umanews-pg-sequence-smoke`
- 数据库容器：`umanews-pg-sequence-db`
- 数据库环境：
  `POSTGRES_DB=horse_news`、`POSTGRES_USER=horse_news`、
  `POSTGRES_PASSWORD=horse_news`、`POSTGRES_CONN_MAX_AGE=0`、
  `POSTGRES_SSLMODE=disable`
- 数据库建立命令：

  ```sh
  docker network create umanews-pg-sequence-smoke
  docker run -d --rm --name umanews-pg-sequence-db \
    --network umanews-pg-sequence-smoke \
    -e POSTGRES_DB=horse_news \
    -e POSTGRES_USER=horse_news \
    -e POSTGRES_PASSWORD=horse_news \
    postgres:16-alpine
  ```

## TC-01 精确失败用例

- 命令（修复前 RED 与修复后 GREEN 使用相同命令）：

  ```sh
  docker run --rm --network umanews-pg-sequence-smoke \
    -v "$PWD:/app" -w /app/server \
    -e DB_ENGINE=postgres \
    -e POSTGRES_HOST=umanews-pg-sequence-db \
    -e POSTGRES_DB=horse_news \
    -e POSTGRES_USER=horse_news \
    -e POSTGRES_PASSWORD=horse_news \
    -e POSTGRES_CONN_MAX_AGE=0 \
    -e POSTGRES_SSLMODE=disable \
    umanews-five-region-rereview:local \
    python manage.py test \
    stable.test_multiregion_attribution_change.AttributionRunLedgerTests.test_all_articles_commit_only_updates_attribution \
    -v 2
  ```

- RED：修复前错误为 `duplicate key value violates unique constraint "stable_termentry_pkey"`，
  `Key (id)=(1) already exists`，发生在 `add_term("Prix de Diane", ...)`。
- GREEN：移除不必要的序列重置后用例通过。

## TC-02 整类回归

- 命令：

  ```sh
  docker run --rm --network umanews-pg-sequence-smoke \
    -v "$PWD:/app" -w /app/server \
    -e DB_ENGINE=postgres \
    -e POSTGRES_HOST=umanews-pg-sequence-db \
    -e POSTGRES_DB=horse_news \
    -e POSTGRES_USER=horse_news \
    -e POSTGRES_PASSWORD=horse_news \
    -e POSTGRES_CONN_MAX_AGE=0 \
    -e POSTGRES_SSLMODE=disable \
    umanews-five-region-rereview:local \
    python manage.py test \
    stable.test_multiregion_attribution_change.AttributionRunLedgerTests \
    -v 1
  ```

- 预期：全部通过，证明事务、lease、resume、manifest drift 与 attribution-only commit 行为保持。

## TC-03 多地区归属回归

- 命令：

  ```sh
  docker run --rm --network umanews-pg-sequence-smoke \
    -v "$PWD:/app" -w /app/server \
    -e DB_ENGINE=postgres \
    -e POSTGRES_HOST=umanews-pg-sequence-db \
    -e POSTGRES_DB=horse_news \
    -e POSTGRES_USER=horse_news \
    -e POSTGRES_PASSWORD=horse_news \
    -e POSTGRES_CONN_MAX_AGE=0 \
    -e POSTGRES_SSLMODE=disable \
    umanews-five-region-rereview:local \
    python manage.py test \
    stable.test_multiregion_attribution_change \
    stable.test_attribution_gold_review \
    stable.test_race_live_multiregion_pipeline \
    stable.test_race_live_multiregion_selector \
    -v 1
  ```

- 预期：全部通过。

## TC-04 SQLite 回归

- 完整模块命令：

  ```sh
  docker run --rm -v "$PWD:/app" -w /app/server \
    -e DB_ENGINE=sqlite \
    -e SQLITE_DB_PATH=/tmp/sequence.sqlite3 \
    umanews-five-region-rereview:local \
    python manage.py test stable.test_multiregion_attribution_change -v 1
  ```

- 预期：非 PostgreSQL-only 测试全部通过。

## TC-05 静态门禁

- 命令：

  ```sh
  docker run --rm -v "$PWD:/app" -w /app/server \
    -e DB_ENGINE=sqlite \
    -e SQLITE_DB_PATH=/tmp/sequence-drift.sqlite3 \
    umanews-five-region-rereview:local \
    python manage.py makemigrations --check --dry-run

  docker run --rm -v "$PWD:/app" -w /app/server \
    -e DB_ENGINE=sqlite \
    -e SQLITE_DB_PATH=/tmp/sequence-check.sqlite3 \
    umanews-five-region-rereview:local \
    python manage.py check
  ```

- 预期：`No changes detected`。

## 证据记录

最终 GREEN、回归数量和命令记录在 `rollout.md`；本任务不部署。
