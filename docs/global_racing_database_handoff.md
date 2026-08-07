# 全球赛马数据库接入交接

日期：2026-06-27

## 当前边界

本轮目标原本是按 `香港 -> 英国 -> 法国 -> 美国` 接入真实赛马数据库，并抓取最近 2 个月赛事和所有涉及马匹详情。用户已在本会话中调整执行边界：香港先停在当前点；英国、法国、美国只需要抓取少量真实批次证明接入方式、parser/importer 和审计边界可用，完整大量数据抓取后续新开会话单独执行。

因此当前结论是：

- 不能宣称四地最近 2 个月完整大量爬取已经完成。
- 不能宣称英法美已经完成生产真实网络 commit。
- 可以宣称英法美少量真实 proof 已证明公开入口、字段解析、马匹详情链路和 dry-run 安全边界可用。
- 后续完整大量爬取必须重新执行最新 60 天 plan-only、小批 dry-run、离线审计、备份、锁检查、健康检查和用户显式确认。

## 当前工作树状态

主工作树 `/Users/mentianlu/Code/umanews` 当前仍在较旧 `main` 分支位置，落后 `origin/main`，但已把后续恢复所需内容同步为未提交工作树差异：

- `origin/main` 中已有的外部缓存底座、HKJC importer、模型、迁移、管理命令和相关测试。
- proof 工作树中尚未进入 `origin/main` 的 UK / France / US importer、离线审计命令、fixtures、旧规格流程 归档和 proof JSON。

当前主工作树已补入以下交接文档：

- `docs/global_racing_data_source_spikes.md`：记录 HKJC、Sporting Life、France Galop / Geny、Equibase / DRF / HRN 的真实入口探索、请求次数、字段覆盖和 proof 边界。
- `docs/global_racing_full_crawl_completion_audit.md`：逐项审计完整目标还缺什么，明确 proof 与完整最近 2 个月大量爬取不是同一件事。
- `docs/global_racing_full_crawl_runbook.md`：后续新会话执行完整 plan-only、小批 dry-run、离线审计和生产 commit 门禁的操作手册。
- `docs/global_racing_sync_manifest.md`：记录当前主工作树同步了哪些代码、规格、fixtures、proof 产物、验证命令和剩余门禁。
- `docs/global_racing_next_run_checklist.md`：按 HK -> UK -> France -> US 顺序列出下一轮完整抓取的开跑检查、证据清单和停止条件。
- `docs/global_racing_change_partition.md`：解释当前大工作树差异应如何按 `origin/main` 底座与英法美 proof 追加分层审查。

原始 proof 与实现工作来源于独立工作树：

- `/Users/mentianlu/.codex/worktrees/旧规格流程-ready-20260626/umanews`
- 分支：`codex/start-hkjc-global-spikes`
- 相关证明文件：
  - `runtime/global_racing_import/proof-20260627/uk/uk-race-url-proof.json`
  - `runtime/global_racing_import/proof-20260627/france-geny/france-geny-partants-proof.json`
  - `runtime/global_racing_import/proof-20260627/us-hrn/us-hrn-race-id-proof.json`
  - `runtime/global_racing_import/proof-20260627-audit.json`

上述 proof JSON 也已同步到当前主工作树的同名 `runtime/global_racing_import/` 路径，便于离线审计命令直接复跑。

## 当前主树验证结果

同步后已在 `/Users/mentianlu/Code/umanews` 使用 Codex bundled Python 和 SQLite / eager Celery 设置完成以下验证：

- `python server/manage.py check`：通过，`0` issues。
- `stable.tests.ExternalHorseDataImportTests`：通过，`9` 项。
- `stable.tests.HKJCExternalDataImportTests`：通过，`28` 项。
- `stable.tests.GlobalRacingSpikeIsolationTests`：通过，`2` 项。
- `stable.tests.UKExternalDataImportTests`：通过，`10` 项。
- `stable.tests.FranceExternalDataImportTests`：通过，`14` 项。
- `stable.tests.USExternalDataImportTests`：通过，`12` 项。
- `stable.tests.GlobalRacingImportOutputAuditTests`：通过，`28` 项；审计会忽略只读 batch command artifact，避免命令清单污染 plan/dry-run 覆盖判断。
- `stable.tests.GlobalRacingImporterCommitGateTests`：通过，`14` 项；四地生产 commit 门禁要求严格完成证明、马匹详情覆盖计数、非空基础 coverage，要求 UK/France/US plan-only 命令显式携带 `--allow-network`，并覆盖从 plan JSON 渲染指定 batch 或全部 batches 命令的只读工具及稳定 `suggested_output_file/path`、`tee_command_line`。
- `stable` 完整测试集：通过，`347` 项。
- `audit_global_racing_import_outputs --proof-only --fail-on-incomplete` 复跑 `runtime/global_racing_import/proof-20260627`：通过 proof 口径，输出仍为 `proof_ready=true`、`proof_blocking_reasons=[]`、`commit_candidate_ready=false`。
- `旧规格流程 validate --all`：通过，`12` 项。
- `git diff --check`：通过。

以上验证证明当前主工作树已经能加载外部缓存底座、HKJC、UK/France/US importer、proof-only 审计命令和相关 fixture 测试；它仍不证明完整最近 2 个月大量爬取或生产 commit 已完成。

## 已证明内容

### 香港 HKJC

- HKJC 真实 HTML 入口、赛事结果页、马匹详情页、dry-run 和批次控制已经建立。
- 生产前 dry-run 进度曾覆盖前 `120/144` 场，未 commit。
- 用户已要求香港先抓到这里，不在本会话续跑。

### 英国 Sporting Life

- 过滤英国赛场后的最近 60 天 plan-only 为 `35` 场。
- racecard dry-run 已覆盖 `35/35` 场。
- 两组精确 `race_urls` 全量 profile proof 分别覆盖 `46/46` 与 `59/59` 匹唯一马，证明 `racecard -> runners/results -> horse profile` 闭环可用。
- 2026-06-27 少量复核 proof 返回 `200`，因 `--limit-horses 1` 正确标记为 incomplete，进入 proof-only 而不是 commit 候选。

### 法国 Geny

- France Galop today 入口可用，但官方历史入口受登录限制；最近 2 个月历史窗口以 Geny 作为当前主候选。
- Geny 已证明日期页、partants、results、horse profile 入口可解析。
- 2026-06-27 少量复核 proof 覆盖 `partants -> results -> horse` 请求链路，返回 `200`，因 `--limit-horses 1` 正确标记为 incomplete。
- 后续完整爬取建议从 `10` 秒/请求起步，遇到 `429` 必须停止当前批次并保留 partial 证据。

### 美国 Horse Racing Nation

- Equibase 当前返回防护页，DRF entries/results 为 JS 应用壳；当前主候选为 Horse Racing Nation。
- HRN 已证明日期/track-day、runner/result table 和 horse profile 入口可解析。
- 2026-06-27 少量复核 proof 覆盖 `track_day -> horse` 请求链路，返回 `200`，因 `--limit-horses 1` 正确标记为 incomplete。

## 离线审计结论

三地少量 proof-only 审计已通过，审计口径为：

- `proof_ready=true`
- `proof_blocking_reasons=[]`
- `commit_candidate_ready=false`
- `handoff_decision=proof_only_ready_not_commit_candidate`
- `handoff_decision_reasons` 包含：
  - `proof-only audit passed`
  - `commit audit still blocked`
  - `complete 60-day crawl and commit gate remain required`

这表示英法美真实接入可用，但完整两个月大量爬取和生产写库门禁仍未完成。

## 后续完整大量爬取前置条件

下一会话继续完整抓取时，应按地区分别完成：

1. 重新生成最新最近 60 天 `plan-only`。
2. 按 plan 输出的小批次执行 dry-run。
3. 确认所有批次 `completion.is_complete=true`。
4. 确认所有涉及马匹 profile 或等价详情字段已覆盖。
5. 使用离线审计确认 `commit_candidate_ready=true` 且 `blocking_reasons=[]`。
6. 生产写库前完成数据库备份、导入锁检查、健康检查和用户显式确认。
7. 写库后记录 run_id、表计数、coverage_stats、请求数量、失败摘要、锁释放和回滚口径。

## 禁止误用

- 不得把少量 proof 当成最近 2 个月完整爬取完成。
- 不得把 fixture/mock commit 测试当成生产真实网络 commit。
- 不得把 `completion.is_complete=false` 的批次纳入 commit 候选。
- 不得在本会话继续扩大 UK/France/US 的完整大量爬取范围。
- 不得把外部数据库接入加入 Celery Beat、新闻抓取、自动发布或 QQ 推送链路。
