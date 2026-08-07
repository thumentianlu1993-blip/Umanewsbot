# 全球赛马数据库变更分层说明

日期：2026-06-27

## 背景

当前主工作树 `/Users/mentianlu/Code/umanews` 的本地 `main` 落后 `origin/main`。为了让后续会话能从当前工作树恢复全球赛马数据库接入工作，已把两类内容同步成未提交工作树差异：

1. `origin/main` 已有的外部缓存底座、HKJC importer、迁移、fixtures、旧规格流程 归档和相关测试。
2. proof 工作树里的 UK / France / US importer、离线审计命令、fixtures、proof JSON 和交接文档。

因此不要直接把“相对本地旧 `HEAD` 的大 diff”当成同一件新改造审查；应先分层。

## 建议审查基线

### 第一层：先对齐 `origin/main`

本地 `main` 当前落后 `origin/main`。相对旧 `HEAD` 出现的大量文件，包括外部缓存底座、HKJC importer、历史 旧规格流程 归档、QQ 推送、前台信息流等，很多已经属于 `origin/main`。

后续若要整理 PR 或提交，建议先让工作树基线对齐 `origin/main`，再审查全球赛马数据库新增部分。不要把 `origin/main` 已有内容和本轮 UK / France / US proof 追加混成一个审查单元。

### 第二层：全球赛马数据库 proof 追加

相对 `origin/main`，本轮真正需要重点审查的全球赛马数据库追加集中在：

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
- `旧规格流程/specs/real-global-racing-data-ingestion/`
- `旧规格流程/changes/archive/2026-06-26-connect-real-global-racing-databases/`
- `runtime/global_racing_import/proof-20260627/`
- `runtime/global_racing_import/proof-20260627-audit.json`
- `docs/global_racing_*.md`

这些内容的目标是证明英法美真实入口、parser/importer、proof-only 审计和后续完整抓取门禁可用；它们不证明最近 60 天完整大量抓取已经完成。

## 建议提交拆分

如果后续要整理提交或 PR，建议拆成以下顺序：

1. **对齐基础分支**：先处理本地 `main` 落后 `origin/main` 的问题，避免把既有线上基线误当新改动。
2. **同步全球赛马 proof 代码**：提交 UK / France / US importer、离线审计命令、fixtures、测试和 `real-global-racing-data-ingestion` 规格归档。
3. **同步 proof 产物**：提交 `runtime/global_racing_import/proof-20260627*`，并明确这些是 proof-only 证据，不是 commit 候选。
4. **同步文档与门禁**：提交 `docs/global_racing_*`、`docs/current_state.md`、`docs/project_status.md`、`docs/project_overview.md`、`docs/deploy_runbook.md`、`docs/decisions.md` 的交接、运行手册、决策和生产红线。

## 当前已验证

当前主工作树已完成：

- `python server/manage.py check`
- `python server/manage.py test stable`，`327` 项通过
- `python server/manage.py makemigrations --check --dry-run`
- `python server/manage.py migrate --plan`
- `旧规格流程 validate --all`
- `audit_global_racing_import_outputs --proof-only --fail-on-incomplete`
- proof JSON 按完整 commit 候选口径审计会被正确阻断
- `git diff --check`

这些验证证明当前代码和文档可作为后续完整抓取会话的恢复基线。按 `2026-06-27` 用户调整后的目标，本轮只要求确认四地真实抓取能力可用，不要求完成最近 60 天完整大量爬取或生产 commit；能力确认目标已可关闭。

## 2026-06-27 review 结论

- 必须保留：四地 importer、真实来源 fixtures、`External*` 缓存模型与写库门禁、proof-only 离线审计、batch command 渲染器、旧规格流程 `real-global-racing-data-ingestion` 规格和 `docs/global_racing_*` 交接/runbook。这些直接支撑“能力真实可用”和后续完整抓取。
- 不能直接提交当前大工作树：本地 `main` 落后 `origin/main`，相对 `origin/main` 会显示大量已在线上存在的文件被删除，同时本地又有同名未跟踪副本。上线或 PR 前必须先对齐基线或重新整理分支，避免把工作树卫生问题变成删除风险。
- 非本目标必需：QQ 推送、前台信息流、历史 旧规格流程 archive、`docker-compose` OneBot 端口映射等旁支差异不属于全球赛马数据库能力确认范围；后续提交应拆开处理。

## 禁止误判

- 不要把本地旧 `HEAD` 到当前工作树的全部 diff 视为一项单独功能改造。
- 不要把 `origin/main` 已有底座与本轮 proof 追加混为一谈。
- 不要把 `runtime/global_racing_import/proof-20260627` 当作最近 60 天完整抓取结果。
- 不要在缺少 plan-only、完整 dry-run、马匹 profile 覆盖、离线审计和用户确认时执行 `--commit`。
