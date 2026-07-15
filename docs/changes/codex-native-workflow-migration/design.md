# Codex 原生工作流迁移设计

## 原生能力映射

| 阶段 | 首选能力 | 项目 fallback / 约束 |
| --- | --- | --- |
| 探索 | Codex 只读调研、规划 | 高歧义/高风险时 `grill-me-codex`；不使用 OpenSpec explore |
| spec/design | Codex 原生规划 | 写入本目录约定的五份 durable artifacts |
| 方案审核 | Codex 原生方案审核 | 当前无适配能力时自动使用 `plan-eng-review` |
| 测试先行 | Codex 测试能力 | 项目 `tdd` skill 固化 RED/GREEN/REFACTOR 契约 |
| 实现 | Codex subagents | active 期间主代理只可派新 subagent 或等待/接收 |
| 审核 | Codex 原生 `/review` / CLI 审核 | 首审建立独立 reviewer 会话，复审复用该会话并限缩范围 |
| 发布 | Git/部署能力 | 仅接受最新成功 review 后的当前任务用户授权 |

当前环境没有通用 spec/design 或方案审核原生 skill，因此不能虚构 skill 名称；前者使用
原生规划并写 durable artifacts，后者回退项目 `plan-eng-review`。测试阶段保留项目
`tdd` skill 作为显式门禁。

## Skill 归档与替换

- OpenSpec 五个 skills、旧 `grill-me`、OpenSpec 版 `plan-eng-review`、workflow-spine 和旧
  Claude 双阶段 `grill-me-codex` 完整备份至 `archive/disabled-skills/2026-07-15/`。
- `.codex/skills/` 只保留重建后的 Codex 原生 `grill-me-codex`、通用
  `plan-eng-review` fallback 与 `tdd`。
- `AGENTS.md` 和 `docs/codex_workflow.md` 同时列出“不应使用”的 skill 名称，防止旧会话
  仅凭历史提示重新调用。
- 既有 OpenSpec artifacts 不迁移、不删除；在途任务读取它们作为基线后，把新增内容写入
  `docs/changes/<slug>/`。

## Subagent 状态机

主代理只有 `IDLE` 与 `SUBAGENTS_ACTIVE` 两种执行状态。任何用途的第一个 subagent 启动后
立即进入 `SUBAGENTS_ACTIVE`；此时只允许 spawn 新 subagent 或 wait/receive。所有 active
subagent 结束后才回到 `IDLE`，检查其摘要、路径、测试证据和风险。写边界重叠时串行；
实现 agent 禁止 commit/push/deploy/生产写入。同一需求的方案审核与代码审核分别在首次
审核时建立未参与对应工作的 reviewer 会话；后续复审复用各自原会话。只有会话明确不可
恢复时才新建，并记录原因、上轮 findings 与已知问题交接。

复审不是重新执行完整清单：只核对上轮具体漏洞/阻塞项、对应修复和直接触及路径回归。
只有属于当前具体漏洞直接回归的 P0/P1 新问题可以继续阻塞；其他新发现写入后续建议后
结束本轮审核，避免把单点修复扩展成通用安全或发布体系。

## Review sandbox 与不可变范围

CLI review 始终在命令内设置 `-c 'sandbox_mode="read-only"'`，并以启动头实际报告
`sandbox: read-only` 为证据。外层只读不替代内层证据；普通 diff、lint 或测试不冒充原生 review。
contract checker 会先折叠普通空白并移除反斜杠续行，再检查 canonical 文件中的每一个小写
CLI 命令；override 必须紧邻命令名，不能由同文件其他安全示例蒙混。

范围分三类：

- uncommitted：helper 无范围参数；Codex 使用 `--uncommitted`。
- branch/base：先把用户 base ref 解析为 `base_oid`，记录 `merge-base HEAD base_oid`；helper
  审前审后都使用同一个 `--base <base_oid>`，Codex 也只接收该 immutable OID；只允许
  clean tree，binary diff 固定为 `merge_base_oid -> head_oid`。
- commit：先解析 `commit_oid`；helper 与 Codex 审前审后只使用该 OID。

base/commit 均拒绝 staged、unstaged、untracked（ignored 不计），以免 committed scope 与
工作树混合；发布前未提交改动统一使用 uncommitted scope。

helper 每次调用内部连续构造至少两份完整快照。每份重新读取 HEAD、porcelain v2 status、
对应范围的 binary diff 与完整 untracked leaf/ancestor manifest，并在 manifest 前后复核
仓库身份；canonical payload 不一致即 fail closed。base payload 记录输入、resolved OID 与
merge-base，commit payload 记录输入与 OID。

manifest 先收集全部路径 identity，再逐项读取并全局复核，从而捕获“读取第一个文件后，
其他 tracked/untracked/status 内容变化”的竞态。普通祖先目录只记录 type/mode；symlink
只记录 target；regular 使用 `O_NOFOLLOW` 与 lstat/fstat identity。Git 返回的 directory leaf
（如嵌套未跟踪 repo）不递归、不跟随，直接要求显式纳入、移出或单独审核。

## 既有任务迁移

正在执行原子操作或共享维护窗口的任务先到安全检查点。之后读取旧 artifacts，补齐
`test_cases.md`，只为剩余行为获取真实 RED，再分派 subagent，并由该需求既有 reviewer
会话审核。过去没有留下的
RED 不补造，已完成生产动作不重跑。历史文档中的 OpenSpec 操作描述保留为事实，不再是指令。
逐会话/worktree 的状态、handoff 条件和验收方式记录在 `rollout.md`；不批量改写其他现有
worktree，因为这会破坏在途 diff 或共享维护窗口，只能在安全检查点通过 handoff/rebase/
main 同步迁移。

## 可执行治理契约

`.codex/scripts/check_workflow_contract.py` 是 stdlib-only、只读 checker，接受 `--repo-root`
以支持隔离 mutation 测试。它校验七阶段、subagent 静默、原生只读 review、当前任务授权、
完整 fingerprint/approved parent/content hash freeze、staging 前逐字节比较、受检 index
表示转换、外部 clean filter 拒绝、RED 门禁、
reviewer agent 同步契约、在途 rollout、两项 skill 的五份 artifacts 交接、active skill allowlist、归档 14 文件固定
SHA/权限/非 symlink、agent TOML、skill frontmatter、legacy OpenSpec 标识和 durable artifacts。

## 发布闭环

发布门保持简单且可验证：最新成功 review、用户对当前任务的明确授权、实际发布内容未变。
成功 review 记录 scope、完整 fingerprint、approved parent 和 `content_manifest_sha256`；授权后
staging 前以相同 scope 重算，完整 fingerprint 必须与审核基线一致。显式 stage 全部受审改动
后允许 status/index 表示变化；只读 index verifier 要求 HEAD 仍为 approved parent、无 unstaged/
untracked/conflict，并要求 index manifest hash 等于受审 content hash。漏 stage、夹带或内容
变化均使 review 与授权失效，回到同一代码 reviewer 会话按限定范围复审并重新取得授权。

部署后只允许 evidence-only closure：精确文件 allowlist 为 current state、project status、
deploy runbook、必要发布 decisions 和本任务 release report；代码、测试、配置、迁移、spec、
tasks、skills、agents 禁入。证据 patch 复用该需求既有代码 reviewer 会话；超出集合或改变
行为/治理则回到完整 review 与新授权。

## Bootstrap 说明

这次工作本身是在旧流程仍存在时由用户直接发起的迁移。最早编辑发生时，本目录与新规则
尚未存在；设计不追溯性伪造前置门禁。helper 出现后续修订时则严格先补测试、取得 RED、
再实现到 GREEN。

## 第四轮方案审核修复

新增 `.codex/scripts/review_release_transition.py`。现行工作流只使用其只读 index 校验：在
临时 Git repo 中验证完整受审改动可 stage，同时拒绝漏 stage、夹带、内容漂移、错误 approved
parent、unstaged/untracked/conflict。脚本中既有 commit/remote 检查属于早期测试资产，不是
现行发布门禁，也不引入 receipt、remote CAS 或新的 push 协议。

## 审核收敛修复

第五轮方案审核暴露出审核机制自身被不断扩展的问题。现行设计删除 receipt-only、发布 CAS
协议等并非用户七阶段要求的必需门禁，改为方案/代码各自首审建立 reviewer 会话、后续复用，
并把复审范围锁定到上轮具体漏洞、修复和直接触及路径。checker 用正向基线与 mutation 测试
锁定会话连续性、不可恢复交接、P0/P1 新阻塞边界以及旧“每轮全新 reviewer”规则不得回流。
