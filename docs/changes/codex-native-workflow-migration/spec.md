# Codex 原生工作流迁移规格

## 背景与目标

用户要求把 Umanews 的全部既有与未来工作立即切换到 Codex 原生优先的七阶段流程，
并把不再使用的 OpenSpec skills 软删除到不会被自动发现的位置。本 change 只改变项目
协作治理、skills/agents 与审核辅助工具，不改变业务代码或生产运行态。

## Requirements

### Requirement 1：项目探索改用原生调研

- 根据当前任务先做只读调研。
- 需求不清、分支多或风险较高时，可以使用 `grill-me-codex` 逐项向用户确认。
- 禁止使用 `openspec-explore`。

### Requirement 2：spec/design 使用 Codex 原生能力

- 优先使用当前环境提供的 Codex 原生规划能力。
- 持久产物固定为 `docs/changes/<slug>/{spec.md,design.md,test_cases.md,tasks.md,rollout.md}` 五份。
- 禁止使用 `openspec-propose`；没有专用原生 skill 时也不得回退到它。

### Requirement 3：方案审核原生优先

- 优先使用可用的 Codex 原生方案审核能力。
- 若当前没有合适的原生方案审核能力，自动使用项目 `plan-eng-review`。
- 方案 findings 未清零前不得进入开发。

### Requirement 4：测试先行

- 开发前补全完整测试用例和自动测试，实际取得因目标行为未实现而产生的 RED。
- 实现按 GREEN/REFACTOR 推进。
- 只有不改变运行时行为的纯文档或纯配置整理可以记录 RED 不适用；行为性配置不得豁免。

### Requirement 5：实现必须由 subagent 完成

- 根据已审核的 spec/design 分派实现分支任务，主代理只接收结果后统一整合。
- 任意 subagent active 时，主代理只能继续派出新的 subagent，或等待/接收结果；不得执行
  其他工作，即使与该 subagent 无关。
- 实现 subagent 不得 commit、push、部署或写生产。
- 禁止使用 `openspec-apply-change`。

### Requirement 6：审核建立并复用独立 reviewer 会话

- 同一需求首次代码审核派出未参与实现的 reviewer subagent，建立该需求的代码 reviewer
  会话，并实际调用 Codex 原生只读 `/review` 或等价 CLI。
- 有 actionable finding 必须修复；后续代码复审回到同一 reviewer、同一会话与上下文。
  同一需求首次方案审核也建立独立的方案 reviewer 会话，后续方案复审复用该会话。
- 只有原 reviewer 会话明确不可恢复时才允许新建，并记录不可恢复原因、上轮 findings 与
  已知问题交接。
- 复审严格限定为上轮具体漏洞/阻塞项、对应修复及其直接触及路径的回归。只有当前具体
  漏洞的直接 P0/P1 回归可新增阻塞；其他新发现记为后续建议后结束，不扩展成通用加固。
- review 范围必须由稳定指纹锁定；branch/base 与 commit 范围必须使用不可变 OID。
- 所有 canonical 文件中的小写 CLI 命令都必须在空白/反斜杠续行规范化后，立即跟随唯一
  允许的内层 read-only override；任一裸命令均 fail closed。
- branch/base 与 commit 只允许完全 clean 工作树；base diff 严格为 merge-base 到 HEAD，
  未提交发布前改动统一走 `--uncommitted`。

### Requirement 7：发布只接受用户的当前任务授权

- 只有最新成功 review 之后，用户针对当前任务说“上线”“发布吧”或同义语句，才允许
  commit、push、PR、部署、迁移或生产写入。
- 禁止使用 `openspec-archive-change`；发布后通过受限 evidence-only closure 回写事实证据。
- 发布门只要求最新成功审核、当前任务用户明确授权、实际发布内容与审核内容未变。成功
  review 记录完整 fingerprint、approved parent 与 `content_manifest_sha256`；授权后 staging 前
  以相同 scope 重算完整 fingerprint 并与基线一致。显式 stage 全部受审改动后允许 status/index
  表示变化，但 HEAD 必须仍为 approved parent、无 unstaged/untracked/conflict，且 index content
  hash 与受审值相同；漏 stage、夹带或内容变化均停止并回到同一 reviewer 会话复审。
- post-release evidence-only closure 复用该需求既有代码 reviewer 会话，仅审核证据范围。

## 兼容与禁用边界

- `openspec-explore`、`openspec-propose`、`openspec-apply-change`、
  `openspec-archive-change`、`openspec-sync-specs` 及旧 workflow-spine 不再使用。
- skills 完整备份到 `archive/disabled-skills/2026-07-15/`；该目录不是 skill discovery 根。
- 既有 `openspec/` artifacts 原地保留为历史或在途上下文，不作为新流程门禁。
- 在途任务先到安全检查点，再只对尚未完成行为应用新流程；不伪造历史 RED，不重做已完成生产动作。

## 验收标准

- `AGENTS.md`、工作流文档、启动模板、agent/skill 配置与状态文档口径一致。
- 五份 durable change artifacts 存在且内容覆盖本规格、设计、测试证据、任务状态与 rollout。
- `grill-me-codex` 的探索交接明确五份 artifacts；`plan-eng-review` 自动读取 `rollout.md`，
  缺失时作为 finding。
- reviewer agent 配置必须与 canonical 工作流使用同一完整 fingerprint、approved parent/
  content hash、staging 前重算和受检 index 表示转换语义。
- checker 必须锁定方案与代码复审的会话复用、不可恢复交接和具体漏洞范围限制，并拒绝
  “每轮新建 reviewer”旧规则回流。
- stdlib-only workflow contract checker 通过，并以 mutation 测试证明关键规则、allowlist、
  固定归档和行为配置 RED 门禁不能被静默放宽。
- 指纹 helper 的自动测试覆盖双完整快照、全局竞态、不可变 base/commit、directory leaf，
  以及外部 clean filter 在未执行副作用前 fail closed。
- TOML、YAML、skill frontmatter、Python 测试、helper smoke 与 `git diff --check` 均通过。
- 本 change 保持未 commit、未 push、未部署、未写生产，直到用户在成功 review 后授权。

## Bootstrap 边界

本次迁移由用户直接要求“即刻应用”而启动。开始迁移时，本文件及新的七阶段流程尚不存在，
因此最早一批治理文档/skill 编辑不可能以前置的 `docs/changes/codex-native-workflow-migration/`
为门禁；本 change 不伪称已经遵守当时尚未建立的规则。目录建立后，后续 helper 强化按
测试先行取得真实 RED/GREEN，并由同一 reviewer 会话按上轮具体漏洞范围继续复审。
