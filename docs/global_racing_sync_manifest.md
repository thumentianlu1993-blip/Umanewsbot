# 全球赛马数据库同步清单

日期：2026-06-27

## 用途

本文记录当前主工作树 `/Users/mentianlu/Code/umanews` 为恢复全球赛马数据库接入工作而同步进来的代码、规格、fixtures、proof 产物和验证状态。

注意：当前本地 `main` 落后 `origin/main`。因此一部分来自 `origin/main` 的既有能力，在本地工作树中会显示为未跟踪文件；这不代表它们全是本轮新设计，而是因为当前本地基线较旧。

## 同步来源

### 来自 `origin/main` 的外部数据底座

这部分提供 `External*` 外部缓存表、导入运行记录、锁、HKJC importer 和既有 OpenSpec / 文档基础：

- `server/stable/models.py`
- `server/stable/migrations/0008_externaldataimportrun_externaldataimportlock_and_more.py`
- `server/stable/management/commands/import_external_horse_data.py`
- `server/stable/management/commands/import_hkjc_external_data.py`
- `server/stable/services/external_horse_data.py`
- `server/stable/services/external_hkjc_data.py`
- `server/stable/services/global_racing_spikes.py`
- `server/stable/fixtures/hkjc/`
- `openspec/specs/global-racing-data-import-readiness/`
- `openspec/changes/archive/2026-06-26-start-hkjc-data-import-and-global-spikes/`

### 来自 proof 工作树的英法美接入与审计

来源工作树：

- `/Users/mentianlu/.codex/worktrees/openspec-ready-20260626/umanews`
- 分支：`codex/start-hkjc-global-spikes`

同步内容：

- `server/stable/management/commands/audit_global_racing_import_outputs.py`
- `server/stable/management/commands/import_uk_external_data.py`
- `server/stable/management/commands/import_france_external_data.py`
- `server/stable/management/commands/import_us_external_data.py`
- `server/stable/services/external_uk_racing_data.py`
- `server/stable/services/external_france_racing_data.py`
- `server/stable/services/external_us_racing_data.py`
- `server/stable/fixtures/uk/`
- `server/stable/fixtures/france_galop/`
- `server/stable/fixtures/us_hrn/`
- `openspec/specs/real-global-racing-data-ingestion/`
- `openspec/changes/archive/2026-06-26-connect-real-global-racing-databases/`

### proof 产物

- `runtime/global_racing_import/proof-20260627/uk/uk-race-url-proof.json`
- `runtime/global_racing_import/proof-20260627/france-geny/france-geny-partants-proof.json`
- `runtime/global_racing_import/proof-20260627/us-hrn/us-hrn-race-id-proof.json`
- `runtime/global_racing_import/proof-20260627-audit.json`

### 交接文档

- `docs/global_racing_database_handoff.md`
- `docs/global_racing_data_source_spikes.md`
- `docs/global_racing_full_crawl_completion_audit.md`
- `docs/global_racing_full_crawl_runbook.md`
- `docs/global_racing_sync_manifest.md`
- `docs/global_racing_next_run_checklist.md`
- `docs/global_racing_change_partition.md`

## 当前验证

当前主工作树已经完成以下本地验证：

- `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python server/manage.py check`：通过，`0` issues。
- `stable.tests.ExternalHorseDataImportTests`：通过，`9` 项。
- `stable.tests.HKJCExternalDataImportTests`：通过，`28` 项。
- `stable.tests.GlobalRacingSpikeIsolationTests`：通过，`2` 项。
- `stable.tests.UKExternalDataImportTests`：通过，`10` 项。
- `stable.tests.FranceExternalDataImportTests`：通过，`14` 项。
- `stable.tests.USExternalDataImportTests`：通过，`12` 项。
- `stable.tests.GlobalRacingImportOutputAuditTests`：通过，`28` 项；新增门禁覆盖 plan-only 必须有请求证据且请求状态成功，非 plan 批次必须有请求证据、请求状态成功、`races/entries/results/horses` coverage 非空，并忽略只读 batch command artifact。
- `stable.tests.GlobalRacingImporterCommitGateTests`：通过，`14` 项；四地 importer 生产 commit 只接受 `completion.is_complete=true` 的严格布尔完成证明，拒绝受限 `stop_reason`、马匹详情缺口、缺少可解析马匹详情覆盖计数或缺少 `races/entries/results/horses` 基本覆盖的 payload，要求 UK/France/US plan-only 命令显式携带 `--allow-network`，并覆盖从 plan JSON 渲染指定 batch 或全部 batches 命令的只读工具及稳定 `suggested_output_file/path`、`tee_command_line`。
- `audit_global_racing_import_outputs --proof-only --fail-on-incomplete` 复跑 `runtime/global_racing_import/proof-20260627`：通过 proof 口径，`proof_ready=true`、`proof_blocking_reasons=[]`、`commit_candidate_ready=false`。
- `openspec validate --all`：通过，`12` 项。
- `stable` 完整测试集：通过，`347` 项。
- `python server/manage.py makemigrations --check --dry-run`：通过，`No changes detected`。
- `python server/manage.py showmigrations stable`：当前本地 SQLite 已应用到 `0007`；同步进来的 `0008` 至 `0013` 处于未应用状态，符合“代码已同步但当前本地库未执行新迁移”的状态。
- `python server/manage.py migrate --plan`：通过，可列出 `0008` 至 `0013` 的待执行迁移计划，包含外部缓存表、自动发布门禁、QQ 推送、来源语言/地区字段、`TermAlias` 和来源字段调整。
- `openspec/changes/archive/2026-06-26-connect-real-global-racing-databases/tasks.md` 已复核并校正法国、美国任务标题，使其明确停在用户新 proof 边界，不再暗示最近 2 个月完整拆批 dry-run 已完成。
- `git diff --check`：通过。

## 命令入口核对

已用 `python server/manage.py <command> --help` 核对后续 runbook 依赖的关键参数，当前主树均支持：

- `import_hkjc_external_data`
  - 范围与批次：`--recent-days`、`--start-date`、`--end-date`、`--race-ids`、`--skip-races`、`--plan-only`
  - 安全与限量：`--allow-network`、`--commit`、`--limit-races`、`--limit-horses`、`--max-requests`
- `import_uk_external_data`
  - 范围与批次：`--recent-days`、`--start-date`、`--end-date`、`--race-urls`、`--skip-races`、`--plan-only`、`--batch-size`
  - 安全与限量：`--allow-network`、`--commit`、`--limit-races`、`--limit-horses`、`--max-requests`
- `import_france_external_data`
  - 来源与范围：`--source`、`--race-date`、`--recent-days`、`--start-date`、`--end-date`
  - 精确批次：`--partants-urls`、`--skip-races`、`--plan-only`、`--batch-size`
  - 安全与限量：`--allow-network`、`--commit`、`--limit-races`、`--limit-horses`、`--max-requests`
- `import_us_external_data`
  - 范围与批次：`--race-date`、`--recent-days`、`--start-date`、`--end-date`、`--seed-track`、`--race-ids`、`--skip-races`、`--plan-only`、`--batch-size`
  - 探索限制：`--limit-tracks`，仅用于 proof 或探索，不得用于完整 commit 候选 plan
  - 安全与限量：`--allow-network`、`--commit`、`--limit-races`、`--limit-horses`、`--max-requests`
- `audit_global_racing_import_outputs`
  - 审计输入：`--input-dir`、`--pattern`
  - 门禁：`--fail-on-incomplete`
  - proof 口径：`--proof-only`、`--expected-sources`、`--expected-request-types`

这表示 `docs/global_racing_full_crawl_runbook.md` 中的主要后续执行入口与当前代码一致。若后续继续完整大量爬取，仍应在正式运行前先用 `--help` 和小样本命令再次确认当前部署版本。

## 防误用验证

已确认 `runtime/global_racing_import/proof-20260627` 只能通过 proof-only 口径，不能通过完整 commit 候选口径：

```bash
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python server/manage.py audit_global_racing_import_outputs \
  --input-dir runtime/global_racing_import/proof-20260627 \
  --pattern '*/*.json' \
  --fail-on-incomplete
```

该命令按预期失败，阻断原因包括：

- `missing plan file`
- `mixed sources geny_france,horse_racing_nation,sporting_life`
- 三个 proof 文件均为 `completion.is_complete=false`
- 英国和美国 proof 中 `horse_profiles_fetched` 少于 `unique_horses_found`

因此这组三地 proof 只能用于证明真实入口、parser/importer 和 proof-only 审计可用，不得用于生产 commit 候选，也不得宣称最近 2 个月完整大量爬取完成。

## 尚未完成

以下内容仍未完成，不能因为当前主树已有代码和 proof 产物就宣称目标完成：

- 香港最近 60 天剩余比赛的完整 dry-run / commit 门禁。
- 英国最近 60 天所有涉及马匹 profile 的完整补齐。
- 法国最近 60 天完整 plan-only、小批 dry-run、所有涉及马匹 profile 或等价详情字段覆盖。
- 美国最近 60 天完整日期/赛场覆盖策略、小批 dry-run、所有涉及马匹 profile 覆盖。
- 每地 `audit_global_racing_import_outputs --fail-on-incomplete` 的 commit 候选审计：`commit_candidate_ready=true` 且 `blocking_reasons=[]`。
- 任何生产写库前的备份、锁检查、健康检查、用户显式确认和写库后表计数 / run_id / 回滚口径记录。

## 后续建议

后续新会话若继续完整大量爬取，应优先从 `docs/global_racing_next_run_checklist.md` 开跑，并对照 `docs/global_racing_full_crawl_runbook.md` 执行具体命令；不要直接从 proof JSON 或 fixture 测试进入生产 commit。完整执行顺序仍为：

1. 香港停点确认或重新 plan-only。
2. 英国最新 60 天 plan-only 与 profile 补齐。
3. 法国 Geny 最新 60 天 plan-only 与低频小批 dry-run。
4. 美国 HRN 最新 60 天 plan-only 与低频小批 dry-run。
5. 每地离线审计通过后，再单独讨论是否生产 commit。
