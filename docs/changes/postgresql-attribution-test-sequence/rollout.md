# PostgreSQL 归属测试序列发布与验证记录

## 生效边界

本变更只影响 Django 测试基础设施，不影响生产运行时、模型、迁移、数据库数据或配置。

## RED 证据

- 日期：2026-07-20
- 数据库：隔离临时 `postgres:16-alpine` 容器 `umanews-pg-sequence-db`
- 网络：隔离 Docker 网络 `umanews-pg-sequence-smoke`
- 应用镜像：`umanews-five-region-rereview:local`
- 数据库环境：
  `DB_ENGINE=postgres`、`POSTGRES_HOST=umanews-pg-sequence-db`、
  `POSTGRES_DB=horse_news`、`POSTGRES_USER=horse_news`、
  `POSTGRES_PASSWORD=horse_news`、`POSTGRES_CONN_MAX_AGE=0`、
  `POSTGRES_SSLMODE=disable`
- 范围：
  `AttributionRunLedgerTests.test_all_articles_commit_only_updates_attribution`
- 完整命令：

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

- 结果：`1` 个测试，`1` 个 error。
- 根因证据：`stable_termentry_pkey` 主键冲突，PostgreSQL 报告
  `Key (id)=(1) already exists`；调用点为测试辅助函数 `add_term()`。
- 复核：该类没有固定主键数值断言，只使用对象实际生成的 ID。

## GREEN 与回归

- PostgreSQL 16 精确用例：`1/1` 通过。
- PostgreSQL 16 `AttributionRunLedgerTests`：`15/15` 通过。
- PostgreSQL 16 `stable.test_multiregion_attribution_change`：`78/78` 通过。
- PostgreSQL 16 相关归属集合（归属主模块、gold review、race-live 多地区 pipeline 与
  selector）：`114/114` 通过。
- SQLite `AttributionRunLedgerTests`：`15/15` 通过。
- SQLite 完整归属主模块：`Ran 78 tests`，`77` 通过，`1` 个 PostgreSQL-only 性能用例按设计
  跳过。
- `python manage.py makemigrations --check --dry-run`：`No changes detected`。
- `python manage.py check`：`System check identified no issues`。

完整测试命令与环境参数记录在 `test_cases.md`；RED 和 GREEN 使用相同的 TC-01 命令，
本次 GREEN 与回归实际执行的完整命令如下：

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

docker run --rm -v "$PWD:/app" -w /app/server \
  -e DB_ENGINE=sqlite \
  -e SQLITE_DB_PATH=/tmp/sequence.sqlite3 \
  umanews-five-region-rereview:local \
  python manage.py test \
  stable.test_multiregion_attribution_change.AttributionRunLedgerTests \
  -v 1

docker run --rm -v "$PWD:/app" -w /app/server \
  -e DB_ENGINE=sqlite \
  -e SQLITE_DB_PATH=/tmp/sequence.sqlite3 \
  umanews-five-region-rereview:local \
  python manage.py test stable.test_multiregion_attribution_change -v 1

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

## 非阻塞观察

为扩大观察范围，曾把既有 `stable.test_multiregion_rollout_change` 一并加入 PostgreSQL
组合。该组合 `129` 个测试中有 `4` 个失败，均为旧 rollout 用例仍期望公开页面展示或 QQ
外部分发，而当前候选已将新闻站点限制为内部使用并阻断外部分发；失败不涉及序列、主键、
run ledger 或本次修改路径。排除该已知策略不兼容套件后，相关归属集合 `114/114` 通过。

此观察不在本次“仅修复测试序列冲突”的范围内；若要恢复或重写旧 rollout 测试，应另起
任务按当前内部使用政策重新定义期望。

## 残余风险

- 修复依赖该测试类继续不以固定主键数值作为合同；当前类已逐项检查且整类回归通过。
- 后续若向该类加入固定主键断言，需要重新评估是否仍可不重置序列。

## 发布状态

- 未 commit。
- 未 push。
- 未创建 PR。
- 未部署。
- 未写生产。
