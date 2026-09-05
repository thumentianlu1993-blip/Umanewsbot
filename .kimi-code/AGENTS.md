# Kimi Code 专属约定：OpenSpec 需求管理流程

本文件是 Kimi Code 在本仓库的专属指令，与根目录 `AGENTS.md` 同时生效。
按仓库分派规则：**Kimi Code 使用 OpenSpec 流程，Codex 使用其原生流程**，两者互不混用。
`openspec/` 目录与 `.kimi-code/` 目录由 Kimi Code 维护，Codex 不会读取。

## 何时走 OpenSpec

- 较大功能、跨模块改动、架构调整和生产高风险变更：先通过 OpenSpec 对齐需求，再进入实现
- 小型修复可以直接处理，但仍须遵守根目录 `AGENTS.md` 的阅读、验证与文档回写要求

## 工作流

顺序：探索 -> 提案（proposal / specs / design / tasks）-> 实现 -> 验证 -> 归档

- OpenSpec 项目上下文与任务路由位于 `openspec/config.yaml`
- openspec CLI 已安装（1.4.1），规格校验使用 `openspec validate --strict`
- 项目级 skills 位于 `.kimi-code/skills/`，通过 `/skill:` 调用：
  - `/skill:openspec-propose` — 创建变更并生成全部 artifact
  - `/skill:openspec-apply-change` — 按 tasks.md 实现变更
  - `/skill:openspec-archive-change` — 验证完成后归档变更
  - `/skill:openspec-explore` — 只探索调研、不实现
  - `/skill:openspec-sync-specs` — 将 delta specs 合并回主 specs
- skill 正文中如出现 `/opsx:*` 字样，那是 Claude Code 的命令形式，在 Kimi Code 中对应上面的 `/skill:openspec-*`

## 产物约定

- `tasks.md` 中的任务必须使用 `(application)`、`(integration)` 或 `(operations)` 域前缀，并按实现先于验证的顺序排列
- OpenSpec 规格中的 `ADDED Requirements / Requirement / Scenario / WHEN / THEN` 等校验关键字保留英文，标题与正文使用中文
- `.kimi-code/skills/openspec-*` 是 openspec CLI 生成的文件，不手工修改；需要刷新时以 `openspec update` 的输出为准重新同步

## 文档回写

任务结束后的文档回写要求以根目录 `AGENTS.md` 的“每次任务结束后必须更新”一节为准。
