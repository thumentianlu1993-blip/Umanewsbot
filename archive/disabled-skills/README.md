# 已停用技能归档

此目录保存从 Umanews 活跃 skill discovery 路径中软删除的历史技能。归档只为保留历史内容和恢复依据，**不属于 `.codex/skills/` 等可发现 skills 路径，禁止主动调用其中的 skill**。

## 2026-07-15 停用清单

归档位置：`archive/disabled-skills/2026-07-15/`

| 技能/目录 | 停用原因 |
| --- | --- |
| `openspec-explore` | 项目探索改用常规调研，必要时使用 `grill-me-codex` 对齐细节 |
| `openspec-propose` | spec/design 改用 Codex 原生能力和仓库约定 |
| `openspec-apply-change` | 实现改为按方案分派 subagent，不再由 OpenSpec apply skill 驱动 |
| `openspec-archive-change` | 提交、发布和收尾只在用户明确授权后按发布流程进行 |
| `openspec-sync-specs` | 新工作流不再通过 OpenSpec skill 同步规格 |
| `workflow-spine` | 旧工作流路由与新规则冲突 |
| `grill-me` | 项目探索统一保留能力更完整的 `grill-me-codex` |
| `plan-eng-review-openspec-legacy` | 原实现依赖 OpenSpec phase/journal/CLI；保留历史后由通用只读审核兜底替换 |
| `grill-me-codex-claude-legacy` | 原实现写 `PLAN.md`/review log 并启动 Claude 与 nested Codex review；完整保留后由 Umanews/Codex 原生只读探索版替换 |

## 恢复原则

1. 不得从本目录直接调用或通过软链接重新暴露归档 skill。
2. 只有用户明确决定恢复某项旧工作流，并确认其与当前 `AGENTS.md` 一致时，才可恢复。
3. 恢复前必须先审核归档内容，移除过时的 OpenSpec 状态推进、自动修改、提交或发布行为。
4. 恢复应复制为新的活跃 skill，并经过独立方案审核；不要修改或删除本归档中的历史副本。
