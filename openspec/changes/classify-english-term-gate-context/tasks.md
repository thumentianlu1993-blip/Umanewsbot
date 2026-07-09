## 1. 英文术语语义判定实现

- [x] 1.1 (integration) 在 `validation.py` 中新增英文术语命中上下文提取结构，包含 matched text、命中位置、前后 token、标题/正文位置和 term metadata
- [x] 1.2 (integration) 实现确定性普通词/专有名词判定规则，覆盖普通词表、页面字段词、日期词、赛事结构词、人名/多词专名和 race/jockey/trainer 强专名
- [x] 1.3 (integration) 将本次审核出的普通英文词集合整理为可 review 的代码常量或 settings 默认值，并保留与 `still_potential_core_terms_breakdown_classified.csv` 的对应说明
- [x] 1.4 (integration) 为无法确定且即将成为 blocker 的命中预留结构化分类接口，默认本地保守返回 `uncertain`，失败或超时不得放行
- [x] 1.5 (integration) 将语义判定接入 `validate_rewrite()`：`common_word` 高置信降级为 warning/info，`proper_noun` 继续 `core_term_missing`，`uncertain` 保持 blocker 或人工审核
- [x] 1.6 (application) 扩展门禁 issue payload 和 validation details，记录 term id、原词、命中文本、上下文、分类、置信度和原因

## 2. 旧 blocker 重校验能力

- [x] 2.1 (application) 优化 `reprocess_term_gate_blocked_articles` 或新增受控命令，先按地区、时间窗、来源、状态和旧 `core_term_missing` 过滤候选
- [x] 2.2 (integration) 为重校验流程复用或批量预加载术语/alias，避免逐篇无界重复加载导致生产 dry-run 过慢
- [x] 2.3 (application) dry-run 输出每篇文章的通过状态、blocker、warning、普通词降级明细、仍阻断专名、地区聚合计数和候选/跳过原因
- [x] 2.4 (application) commit 模式只对完整门禁通过文章调用既有 `apply_validation_outcome()` 并更新 `ranked_revived_at`，不得直接公开发布文章

## 3. 测试覆盖

- [x] 3.1 (application) 添加英文普通词命中测试，确认 `Contact / Number / Live / Were / AGENDA` 类普通上下文不生成 blocker
- [x] 3.2 (application) 添加真实专名测试，确认 `Belmont Stakes / Kentucky Derby / Prix Ganay` 等未保留时继续生成 `core_term_missing`
- [x] 3.3 (application) 添加可双关词低置信测试，确认 `Tuesday / GOOD JOB / Fast Track` 无法确定时不自动放行
- [x] 3.4 (application) 添加地区过滤优先级测试，确认跨地区英文术语仍走 `term_region_excluded`，不进入语义分类
- [x] 3.5 (application) 添加重校验命令 dry-run/commit 测试，覆盖有界候选、无写 dry-run、只恢复完整通过文章
- [x] 3.6 (application) 添加本批审计普通词集合的回归测试或 fixture，确认 `ACE / AGENDA / Contact / Number / Live / Were / Tuesday` 等代表词可按普通上下文降级

## 4. 文档与验收

- [x] 4.1 (operations) 更新 `docs/current_state.md`、`docs/project_status.md` 和 `docs/deploy_runbook.md`，记录实现范围、生产执行边界和 dry-run/commit 操作口径
- [x] 4.2 (application) 执行 `DB_ENGINE=sqlite python manage.py check`
- [x] 4.3 (application) 执行相关 Django 测试，至少覆盖英文术语门禁和重校验命令测试
- [x] 4.4 (operations) 执行 `openspec validate classify-english-term-gate-context --strict` 和 `git diff --check`
- [x] 4.5 (operations) 生产上线前准备只读 dry-run 命令，目标为 7 月 1 日以来香港、英国、美国、法国旧 `core_term_missing` 候选，并明确不执行 commit 直到人工确认
- [x] 4.6 (operations) 用完整 dry-run 对照本批审计投影：生产实际可恢复候选为 `37` 篇，仍阻断 `109` 篇，且真实专名阻断文章不得被普通词规则误放行
