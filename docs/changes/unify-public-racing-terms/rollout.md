# rollout：多语言赛马术语统一与公开内容修复

## 当前状态

- 阶段：`implemented`。
- 用户已于 2026-07-26 明确授权实现；代码已由 Claude subagent 完成实现。
- 实现 worktree: `impl-race-news-quality-20260726`，分支 `codex/impl-race-news-quality-20260726`，
  基线 `origin/main@ef54a183`。
- RED：`test_public_term_consistency.py` 27/32 RED（因 term_consistency 服务模块不存在）。
- GREEN：29/32 GREEN（3 性能测试在 SQLite 预期受限，设计目标 PostgreSQL）。
- 回归：test_english_term_context_gates 所有通过，test_term_gate_reprocessing 所有通过。
  Django check + makemigrations --check --dry-run 通过。
- 新增模型 `TermMappingEvidence` + migration `0060`；
  新增服务 `term_consistency.py`；
  新增 settings 3 项。
- 下一门禁：独立代码 review；commit、push、PR、部署、生产术语写入和历史文章修复仍未授权。

## 分阶段交付

1. 只读生成英皇锦标及相关马匹的术语候选审核包。
2. 实现 resolver 与新文章一致性门禁，默认 shadow。
3. 审核 shadow 冲突和 unresolved，开启新文章 enforce。
4. 对已发布文章生成独立 dry-run 修复包。
5. 历史 apply 在代码发布后另行冻结、审核和授权；不与部署自动绑定。

## 并行与恢复边界

- 当前已知重叠线包括 `normalize-race-and-career-fields`、`fix-external-english-horse-context-gate`、
  `translate-collected-race-horse-names` 和主检出区 `news_reflect`。实现前必须基于最新
  `origin/main` 重做 models/terms/validation/reprocessing/迁移图 overlap；未合并的正式术语、
  occurrence resolver 或 migration 不得被复制成第二套实现。
- 实现使用新的干净隔离工作树，本规划工作树只保留 durable artifacts。
- 若相关线已改变 `TermEntry/TermAlias`、published audit 或人工字段语义，先回到 design 和方案
  reviewer 同一会话复审，不直接适配后开工。

## 回滚

- 关闭一致性 enforce，恢复现有翻译/发布行为。
- 停用错误 alias，不删除源文或证据。
- 历史 apply 使用字段级 ledger 恢复；QQ delivery 和公开时间始终不动。

## 发布前证据

- 正式 mapping 的身份、来源、语言、地区和冲突报告。
- RED/GREEN、性能、受影响回归和公开页面检查。
- published dry-run 中人工字段跳过及状态/QQ 守恒报告。
- reviewer 成功结论、冻结 fingerprint，以及最新 review 后的用户授权。
- 实现完成后更新 `docs/current_state.md`、`docs/decisions.md`、`docs/project_status.md`；实际部署、
  migration、灰度、历史 dry-run/apply 和回滚证据更新 `docs/deploy_runbook.md`。
