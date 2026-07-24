# 代码审核交接：历史新闻正文污染盘点与重处理

## 1. 审核目标

对 `audit-reprocess-historical-news-body-contamination` 的实现进行只读代码审核。
本任务承接前置修复 `fix-news-body-extraction-boundaries`（已部署，HRN 选择器已收紧到 `.article-body`），
完成历史 282 篇 HRN 文章的盘点、候选准备、人审包生成和离线精确写入四个阶段。

当前阶段：实现完成，等待独立 reviewer 执行原生只读 `/review`。

## 2. 工作区

- 仓库根：`/Users/mentianlu/Code/umanews`
- 本任务独立 worktree：
  `/Users/mentianlu/.codex/worktrees/audit-reprocess-historical-news-body-contamination/umanews`
- 分支：`codex/audit-reprocess-historical-news-body-contamination`
- 基线：`origin/main@97dd2350a193c74d5063bf7432a283e4d47f6d0a`

接手后先运行：

```bash
cd /Users/mentianlu/.codex/worktrees/audit-reprocess-historical-news-body-contamination/umanews
git status --short --branch
git rev-parse HEAD origin/main
```

若 `origin/main` 已前进，只读报告差异，不要修改代码。

## 3. 必读文档（按顺序）

1. 本目录 `spec.md` — 规格与失败边界
2. 本目录 `design.md` — 四阶段数据流与字段所有权矩阵
3. 本目录 `test_cases.md` — RED 测试清单（I01–I12, P01–P08, R01–R07, A01–A13, V01–V06）
4. 本目录 `tasks.md` — 任务清单与审批状态
5. 本目录 `rollout.md` — 六阶段发布门禁
6. 本目录 `handoff.md` — 原上下文交接（含生产探索事实与设计决定）
7. `docs/changes/fix-news-body-extraction-boundaries/` 全部文件 — 前置修复

## 4. 实现清单

### 新增文件

| 文件 | 行数（约） | 职责 |
|---|---|---|
| `server/stable/services/news_body_history.py` | ~830 | 核心服务：cohort 冻结、inventory 生成、指纹计算、候选审批校验、rollback artifact 构建、apply/rollback |
| `server/stable/management/commands/inventory_news_body_history.py` | ~60 | `--source-site --max-id --output-dir`，分页只读扫描 |
| `server/stable/management/commands/apply_news_body_history_batch.py` | ~80 | `--manifest --manifest-sha256 --rollback-dir [--commit]`，单事务校验+写入 |
| `server/stable/management/commands/rollback_news_body_history_batch.py` | ~55 | `--rollback-manifest --manifest-sha256 [--commit]`，CAS 回滚 |
| `server/stable/test_news_body_history.py` | ~820 | 39 项测试 |

### 未修改的既有文件

无。本任务未改动任何既有代码、migration、settings、模板或配置。

## 5. 测试覆盖

```bash
cd /Users/mentianlu/.codex/worktrees/audit-reprocess-historical-news-body-contamination/umanews
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true \
  /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_news_body_history stable.test_news_content_boundaries --noinput
```

当前结果：**84 项全部 GREEN**（39 新 + 45 既有正文边界回归）。

### 5.1 新测试类与验证范围

| 测试类 | 测试数 | 覆盖的 test_cases |
|---|---|---|
| `NewsBodyHistoryInventoryTests` | 15 | I01–I12 |
| `NewsBodyHistoryPrepareTests` | 5 | P01, P04–P06, P08 |
| `NewsBodyHistoryReviewPackageTests` | 5 | R01–R03, R05, R07 |
| `NewsBodyHistoryApplyTests` | 8 | A01–A03, A05, A07–A10 |
| `NewsBodyHistoryRollbackTests` | 3 | V04–V06 |
| `NewsBodyHistoryCommandTests` | 3 | 命令级集成 |

### 5.2 既有回归

- `InternationalNewsContentBoundaryTests`：14 项
- `InternationalNewsBodyParseGateTests`：4 项
- `RepairArticleContentBoundariesCommandTests`：13 项
- `HorseRacingNationHistoricalBoundaryScanTests`：5 项
- `ForcePublishedArticleTranslationTests`：9 项

## 6. 关键设计决定与代码地图

### 6.1 四阶段数据流

```
inventory（只读）→ prepare（DTO + pure provider）→ review（人工定稿）→ apply（离线精确写入）
```

实现当前覆盖了 inventory / review / apply / rollback 四个阶段的代码。
prepare 阶段（AI 候选生成）需要在独立的网络授权 Gate 4 中执行，不属于本次工具实现范围。

### 6.2 字段保护矩阵

`PERMANENT_NO_WRITE_FIELDS`（`news_body_history.py:105-130`）：`id/source_site/source_article_id/source_url/public_slug/workflow_status/review_mode/automation_status/published_to_web_at/published_by/manually_edited_fields/title_ja/title_zh/translated_title_zh/rewrite_title_zh/translation_status/translation_error_*/translation_retry_*` 等永久不写。

`ALLOWED_APPROVE_FIELDS`（`:102`）：`body_ja_raw/body_ja_normalized/content_boundary_repair/translated_body_zh/body_zh/translated_summary_zh/summary_zh/push_summary_zh/base_translation_zh/rewrite_body_zh`。

### 6.3 事务安全

1. `build_rollback_artifact()` 在 DB 事务**之前**原子写完整 before 值：`open(wb) → write → flush → fsync → os.replace → directory fsync`
2. `apply_batch(commit=True)` 的事务在管理命令中（`transaction.atomic()`），不在服务函数内
3. 事务内 `select_for_update()` 按 ID 升序锁全集
4. 指纹漂移排除 `updated_at`（auto_now 自然变化），检测 `original_content_html/body_ja_raw/translated_body_zh/body_zh/rewrite_body_zh/manually_edited_fields/workflow_status/translation_status/published_to_web_at`
5. 任一漂移 → `ValueError` → 整批回滚，业务字段和 `OperationLog` 零写入

### 6.4 审批校验（`validate_approved_decisions`）

- 强制 `approve_no_action/keep_manual/reject` 的 `approved_fields` 为空
- 强制 `approve_fields` 的 `approved_fields` 非空且全部在 allowlist 内
- 拒绝重复 ID、未知 decision、空 reviewer/reason
- schema_version 强制为 `APPROVED_MANIFEST_SCHEMA_VERSION` (1)

### 6.5 SQLite 兼容

`generate_inventory()` 中 TranslationRun 去重使用 Python 级 `seen_run_articles` set 替代 PostgreSQL 的 `DISTINCT ON`（`:539-546`），确保本地测试可运行。

## 7. 已知局限

1. **Prepare 阶段未实现**：候选生成（AI 翻译/改写）不在本次工具范围，按 rollout.md 属 Gate 4 独立授权。服务层预留了 `CandidateOutput` dataclass、`compute_before_fingerprint`/`compute_after_fingerprint` 等接口供后续使用。
2. **Review package XLSX 生成未实现**：审批校验逻辑已完整（`validate_approved_decisions`），但 `review.xlsx` 工作簿生成和 submitted workbook 的回读/列验证/证据列一致性检查未在首版实现——当前直接接受 JSON 格式的 `approved_decisions.json`。
3. **Verify 独立命令未拆分**：写后验证（V01–V03）的 checker 逻辑内嵌在 receipt 生成中，未拆为独立 `verify_news_body_history_batch` 命令。
4. **DB read-only 强制角色**：inventory 的只读保证来自"代码不调用 save/delete/create"而非 PostgreSQL `SET TRANSACTION READ ONLY`。design 中要求生产使用专用 SELECT-only 角色，本工具代码未实现连接级只读切换或写探针。
5. **测试仅覆盖 SQLite**：未覆盖真实 PostgreSQL 的事务锁、并发和角色测试。按 rollout.md Gate 1，这些属于生产前验证（tasks 3.2），当前实现仅需本地 GREEN。

## 8. 审核重点

### P0 必查

1. **事务安全**：`apply_batch(commit=True)` 是否在 `select_for_update` 锁内完成所有写入，漂移是否整批零写。
2. **字段保护**：`PERMANENT_NO_WRITE_FIELDS` 是否覆盖了 design 中的所有"永久不自动写"字段；apply 循环中的 `setattr` 是否会意外覆盖这些字段。
3. **Rollback artifact 持久化**：`_atomic_write_json` 的文件 fsync + os.replace + directory fsync 顺序是否正确；是否在 DB 写事务前完成。

### P1 建议

4. **Inventory 穷尽性**：分页逻辑是否保证不重、不漏；`counts` 各项之和是否等于 `cohort.count`。
5. **审批校验完备性**：`validate_approved_decisions` 的拒绝条件是否覆盖 design 中的逐字段前置矩阵。
6. **幂等性**：同一 manifest replay 是否正确拒绝（漂移检测），同一 rollback manifest replay 是否安全。
7. **既有代码回归**：是否无意修改了 `repair_article_content_boundaries` 或其他既有文件。

## 9. 禁止动作

- 不修改应用代码、配置、migration
- 不运行 `--commit` 或任何数据库写入
- 不触网（翻译/改写/抓取 API）
- 不 commit、push、PR、merge、deploy
- 不启动实现 subagent

## 10. 运行命令速查

```bash
WT=/Users/mentianlu/.codex/worktrees/audit-reprocess-historical-news-body-contamination/umanews
PY=/Users/mentianlu/Code/umanews/.venv/bin/python

# Django 检查
cd $WT && DB_ENGINE=sqlite $PY server/manage.py check

# 聚焦测试
cd $WT && DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true \
  $PY server/manage.py test \
  stable.test_news_body_history \
  stable.test_news_content_boundaries --noinput

# 完整 stable 测试（注意：有预存 failure）
cd $WT && DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true \
  $PY server/manage.py test stable --noinput

# diff 检查
cd $WT && git diff --check && git diff --stat HEAD

# 迁移漂移
cd $WT && DB_ENGINE=sqlite $PY server/manage.py showmigrations --list | grep -c '\[ \]'
```

## 11. 审核结论格式

审核完成后请使用以下格式输出：

```
FINGERPRINT_SHA256=<完整 stdout 的 SHA-256>
VERDICT: APPROVED | REVISE
FINDINGS:
- [P0/P1/P2] <文件:行号> — <一句话描述>
  <复现步骤或影响>
```

若 `REVISE`，请列出每条 finding 的具体文件、行号和复现步骤。
