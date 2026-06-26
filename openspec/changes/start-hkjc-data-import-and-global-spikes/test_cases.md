# 测试用例矩阵

本文档记录本 change 的 TDD 红灯用例。当前阶段只写测试，不实现业务代码。

## 1. HKJC 样本导入闭环

- `stable.tests.HKJCExternalDataImportTests.test_hkjc_management_command_stats_run_id_reports_coverage`
  - 目标：commit 后 `--stats-run-id` 能返回 `run_id`、`source`、`status`、`success_count`、`coverage_stats` 和 `error_count`。
  - 当前结果：PASS，作为现有能力的回归保护。
  - 变异点：如果统计命令不限制 HKJC 来源、漏掉 coverage，或成功数和写入数脱节，本用例会失败。

## 2. HKJC 真实网络小样本准备

- `stable.tests.HKJCExternalDataImportTests.test_hkjc_import_options_are_backed_by_runtime_settings`
  - 目标：`HKJC_IMPORT_REQUEST_INTERVAL_SECONDS`、`HKJC_IMPORT_MAX_RACES_PER_RUN`、`HKJC_IMPORT_MAX_HORSES_PER_RUN` 必须进入 Django settings，并被 `HKJCImportOptions.from_settings()` 使用。
  - 当前结果：GREEN，已补齐 `settings.py`、`.env.example` 和 runbook 配置。
  - 变异点：如果生产限速和批量上限只能依赖代码默认值，本用例会失败。

- `stable.tests.HKJCExternalDataImportTests.test_hkjc_network_dry_run_records_request_boundary_without_writing`
  - 目标：`--allow-network` dry-run 必须记录 `network_probe`、请求 URL、状态码、目标类型、目标 ID 和 coverage，且不写 `External*` 表或 `ExternalHorseAlias`。
  - 当前结果：GREEN，`--allow-network` dry-run 会返回 `network_probe` 和请求边界，并保持不写正式表。
  - 变异点：如果网络 dry-run 被实现成占位数据或静默写库，本用例会失败。

## 3. 英法美数据库 spike 隔离

- `stable.tests.GlobalRacingSpikeIsolationTests.test_equibase_spike_records_counts_and_does_not_write_formal_tables`
  - 目标：spike runner 必须记录正式表 before/after 计数，并保持 `ExternalRace`、`ExternalRaceEntry`、`ExternalRaceResult`、`ExternalHorseAlias` 不变。
  - 当前结果：GREEN，`stable.services.global_racing_spikes.run_source_spike()` 会记录正式表 before/after 计数并保持不写表。
  - 变异点：如果 spike 意外 upsert 正式外部缓存或马名索引，本用例会失败。

- `stable.tests.GlobalRacingSpikeIsolationTests.test_uk_fr_us_spikes_reject_commit_mode`
  - 目标：`equibase`、`sporting_life_bha`、`france_galop` 在 spike 阶段必须拒绝 `commit=True`。
  - 当前结果：GREEN，英法美 spike 的 `commit=True` 会被拒绝。
  - 变异点：如果英法美 spike 被误接入正式写库入口，本用例会失败。

## 4. 本轮非目标边界

本轮测试不新增公开比赛页、赛果页、马匹页、今日赛程模块或新闻分发策略断言；这些能力不是本 change 的实现目标。若后续要做前台产品，需要另起 OpenSpec change 并单独补充测试矩阵。

## 当前 RED 命令

```bash
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py test stable.tests.HKJCExternalDataImportTests stable.tests.GlobalRacingSpikeIsolationTests --noinput
```

当前结果：12 个测试全部通过；完整 `stable` 测试通过 246 项。
