# AGENTS.md

## 项目定位

这是一个面向中文用户的日本赛马新闻平台，目标是把日本赛马资讯整理成清晰可读的中文内容，并提供后台审核、网页发布与后续 QQ 群分发能力。

技术栈主干：

- Django
- PostgreSQL
- Celery
- Redis
- Docker Compose
- Nginx

## 当前阶段

当前阶段已经完成：

- 基础采集、翻译、后台、前台链路搭建
- 公网服务器部署
- 正式域名 `umafans.run` / `www.umafans.run` 的 HTTP 接入修复
- 自动化内容运营 + AI 编辑改写 MVP 代码侧落地

下一阶段准备推进：

- 自动化运营 MVP 生产部署、迁移与灰度启用
- HTTPS / 证书接入
- 部署稳定化
- 监控、备份、回滚流程完善

## 工作原则

- 先闭环可用，再谈优化和扩展
- 不轻易重构主干架构
- 不把聊天记录当项目记忆
- 所有关键状态、决策、排查过程都要写回仓库文档
- 做生产相关改动时，优先核对运行态，而不是只看本地代码预期

## Codex 原生工作流

本项目从 `2026-07-15` 起统一使用以下主流程；完整说明见
[`docs/codex_workflow.md`](docs/codex_workflow.md)：

`探索 -> spec/design -> 方案审核 -> 用户确认实现 -> 测试先行 -> 子代理实现 -> 独立 reviewer 会话 /review -> 用户授权后发布`

- 探索阶段使用 Codex 原生只读调研与规划能力。需求不清、决策分支多或风险较高时，可以使用 `grill-me-codex` 逐项确认；禁止使用 `openspec-explore`。
- spec/design 阶段优先使用 Codex 原生规划能力。新任务的持久产物放在 `docs/changes/<slug>/`，至少包含 `spec.md`、`design.md`、`test_cases.md`、`tasks.md`、`rollout.md` 五份 durable artifacts；`tasks.md` 使用 `(application)`、`(integration)` 或 `(operations)` 域前缀，并按“测试 -> 实现 -> 验证”排列。
- 方案审核优先使用可用的 Codex 原生方案审核能力；工作流进入“方案审核”阶段且当前没有合适的 Codex 原生方案审核能力时，自动使用 `plan-eng-review`，无需用户再次点名。首次方案审核建立 reviewer 会话；同一需求的方案复审复用该 reviewer 的同一会话与上下文，仅在会话不可恢复时新建并交接。复审只核对上轮具体 findings、对应修复和直接触及路径；仅直接 P0/P1 回归可新增阻塞，其他新发现记为后续建议并结束。审核结论未通过前不得进入开发。
- 方案审核通过后必须向用户提交根因、最终范围、测试与 RED 方案、历史数据边界、风险/非目标/回滚和 reviewer 结论，并停在“用户确认实现”门禁。只有用户针对当前版本明确回复“确认实现”“开始实现”“继续实现”或同义授权后，才可编写/修改自动化测试、修改应用代码/配置/迁移、启动实现 subagent 或执行历史数据重处理；最初任务描述和探索/规划授权不得视为实现授权。
- 开发前必须补足 `test_cases.md` 和对应自动化测试，并实际看到新增/变更测试因目标能力尚未实现而失败（RED）；再逐项完成 GREEN 和 REFACTOR。只有不改变任何运行时行为的纯文档或纯配置整理，才可以在 `test_cases.md` 中写明 RED 不适用原因，并给出、执行相应验证。feature flag、队列/路由、权限、依赖、容器或部署顺序、数据行为等配置变化不得豁免测试先行。
- 任何 subagent（实现、测试、审核、调研或其他用途）启动后，直到全部 active subagent 结束，主代理只能继续派出新的 subagent，或等待/接收结果；不得读/改文件、跑测试、继续调研、向其他任务发消息、处理用户追加的无关工作或执行其他工具调用。写密集任务默认串行；并行时必须保证文件边界不重叠。
- 实现 subagent 不得 commit、push、部署或写生产；返回内容必须包含摘要、改动路径、测试证据和剩余风险。主代理仅在所有实现 subagent 结束后检查、整合和验证结果。
- 代码首次审核必须派出一个未参与本轮实现的 reviewer subagent，并实际调用 Codex 原生 review。同一需求后续复审必须复用该 reviewer 的同一会话与上下文；只有 reviewer 明确确认会话不可恢复时才能新建，并记录原因、上轮 findings 与已知问题交接。复审范围只包括上轮具体 actionable findings（漏洞/阻塞项）、对应修复和修复直接触及路径的回归；仅当前漏洞的直接 P0/P1 回归可新增阻塞，其他新发现记录为后续建议后结束本需求审核。具体命令、fingerprint 与 fail-closed 规则见 `docs/codex_workflow.md` 第 7 节。

<!-- WORKFLOW_CONTRACT:REVIEW_COMMANDS:START -->
- `codex review -c 'sandbox_mode="read-only"' --uncommitted`
- `codex review -c 'sandbox_mode="read-only"' --base <base_oid>`
- `codex review -c 'sandbox_mode="read-only"' --commit <commit_oid>`
<!-- WORKFLOW_CONTRACT:REVIEW_COMMANDS:END -->

<!-- WORKFLOW_CONTRACT:RELEASE_AUTHORIZATION:START -->
当前任务发布授权必须在最新一轮成功 review 之后取得。
<!-- WORKFLOW_CONTRACT:RELEASE_AUTHORIZATION:END -->

review 前的旧授权、`let's go`、其他任务的授权和历史文档中的词均无效。最新成功 review
后若受审内容发生变化，必须回到同一 reviewer 会话复审变更及其直接触及路径，并重新取得授权。

<!-- WORKFLOW_CONTRACT:FINGERPRINT_FREEZE:START -->
- 成功 review 记录受审 scope、完整 fingerprint、approved parent（审核时 HEAD）和 approved content hash（`content_manifest_sha256`），作为当前任务最新审核基线。
- 用户授权后、staging 前完整 fingerprint 必须用相同 scope 重算并与审核基线逐字节一致；不一致则停止。
- 显式 stage 全部受审改动后，允许 status/index 表示发生变化；但 HEAD 必须仍为 approved parent，且无 unstaged、untracked 或 conflict，index 的 `content_manifest_sha256` 必须与 approved content hash 一致。漏 stage、夹带或内容变化均停止。
- 任何实际内容差异都会使该轮 review 与授权失效；必须回到同一 reviewer 会话，仅复审变化、对应修复和直接触及路径，并在成功后重新取得当前任务授权。
<!-- WORKFLOW_CONTRACT:FINGERPRINT_FREEZE:END -->

部署后一次性 evidence-only closure 的文件 allowlist 也是精确全集：

<!-- WORKFLOW_CONTRACT:EVIDENCE_ALLOWLIST:START -->
- `docs/current_state.md`
- `docs/project_status.md`
- `docs/deploy_runbook.md`
- `docs/decisions.md（仅必要发布决策）`
- `docs/changes/<slug>/release_report.md`
<!-- WORKFLOW_CONTRACT:EVIDENCE_ALLOWLIST:END -->

`docs/decisions.md` 仅可记录发布时不可避免且已经发生的必要决策，不得借此修改治理规则。evidence-only patch 必须仅追加事实证据，并复用同一需求既有代码 reviewer 会话审核该证据范围；以下类别一律不得进入该通道：

<!-- WORKFLOW_CONTRACT:EVIDENCE_FORBIDDEN:START -->
- 代码
- 测试
- 配置
- 迁移
- spec
- tasks
- skills
- agents
<!-- WORKFLOW_CONTRACT:EVIDENCE_FORBIDDEN:END -->

若证据修复超出 allowlist、触及上述禁入类别或改变行为/治理，必须回到完整 review，并在成功 review 后重新取得当前任务授权。证据 commit 自身 SHA 仅在最终回复/PR 元数据中报告，不为写回自身 SHA 再制造 patch。
- 小型修复也不得绕过测试先行、subagent 实现、独立 review 和发布授权；可按风险缩短 spec/design，但必须保留可追溯记录。

### OpenSpec 兼容边界

- `openspec/` 下既有规格和在途 change 原地保留，作为历史或在途上下文；它们可继续被读取，但后续工作按上述新流程推进。
- 对 `2026-07-15` 时仍在途的任务，不中断正在执行的原子操作或共享维护窗口；先到达安全检查点，再切换到新流程。切换后读取现存规格，补齐或更新 `test_cases.md`，对尚未实现的行为取得真实 RED，再由 subagent 实现并由该需求代码 reviewer 会话审核。不得为补流程伪造已经错过的历史 RED，也不得重做已完成的生产动作。
- 禁止调用 `openspec-explore`、`openspec-propose`、`openspec-apply-change`、`openspec-archive-change`、`openspec-sync-specs`，也不再把 OpenSpec CLI、phase、journal 或 workflow-spine 作为新流程门禁。
- `openspec/config.yaml` 仅为兼容既有 artifacts 保留，不代表 OpenSpec 仍是项目主工作流。

## 开始任何任务前必须先阅读

1. [docs/project_overview.md](E:/Codex/docs/project_overview.md)
2. [docs/current_state.md](E:/Codex/docs/current_state.md)
3. [docs/decisions.md](E:/Codex/docs/decisions.md)
4. [docs/deploy_runbook.md](E:/Codex/docs/deploy_runbook.md)
5. [docs/session_bootstrap.md](E:/Codex/docs/session_bootstrap.md)
6. [docs/codex_workflow.md](docs/codex_workflow.md)
7. 如涉及部署或运维，再补充阅读：
   - [docs/deploy_production.md](E:/Codex/docs/deploy_production.md)
   - [docs/alicloud_hongkong_step_by_step.md](E:/Codex/docs/alicloud_hongkong_step_by_step.md)
   - [docs/rollback_guide.md](E:/Codex/docs/rollback_guide.md)
   - [docs/backup_recovery.md](E:/Codex/docs/backup_recovery.md)

补充约定：

- [docs/current_state.md](E:/Codex/docs/current_state.md) 是当前真实工作状态主文档
- [docs/project_status.md](E:/Codex/docs/project_status.md) 是面向项目全局的概览/摘要
- 两者如有重复或冲突，以 [docs/current_state.md](E:/Codex/docs/current_state.md) 为准

## 输出风格

- Codex 新增或维护的仓库文档、规格与设计产物、代理说明和面向协作者的文字默认使用中文
- 命令、代码标识符、协议字段、第三方工具要求的机器语法，以及无法合理翻译的专有名词可以保留英文
- 既有 OpenSpec 规格中的 `ADDED Requirements / Requirement / Scenario / WHEN / THEN` 等校验关键字必须保留，但其标题和正文内容使用中文
- 先确认当前真实状态，再给建议
- 涉及生产问题时，优先给文件、命令、路由、配置片段级别的说明
- 如果用户要求部署/排障，必须区分：
  - 仓库当前预期
  - 服务器当前运行态
- 不给模糊候选结论；如果有多个入口或路径，必须明确“本次验收以哪个为准”

## 每次任务结束后必须更新

发布任务按 `docs/codex_workflow.md` 的 evidence-only closure 回写：完整审核范围（包括
治理文件）在发布前冻结，部署后只向获准的状态/运维文档追加事实证据并复用同一需求既有代码 reviewer 会话
审核；证据 review 通过后提交该文档 patch 即完成收尾，不再为记录证据 commit 自身 SHA
产生递归更新。会改变治理、产品或链路的决策必须在成功 review 前写入并纳入审核；部署时
已经发生且不可避免的必要发布决策可按受检 allowlist 追加到 `docs/decisions.md`，但不得
改变治理规则或行为，且必须进入 evidence review。

- [docs/current_state.md](E:/Codex/docs/current_state.md)
- [docs/decisions.md](E:/Codex/docs/decisions.md)（治理/行为决策须在成功 review 前纳入冻结；部署后仅限必要发布决策证据）
- [docs/deploy_runbook.md](E:/Codex/docs/deploy_runbook.md)（若涉及部署、排障、运维）
- [docs/project_overview.md](E:/Codex/docs/project_overview.md)（若产品定位或链路变化，须在成功 review 前更新并纳入冻结范围）
- [docs/project_status.md](E:/Codex/docs/project_status.md)（保留为项目级概览/摘要，如与 current_state 重复，以 current_state 为准）
