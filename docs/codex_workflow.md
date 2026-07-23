# Codex 项目工作流

## 适用范围

本流程自 `2026-07-15` 起适用于 Umanews 项目全部既有和未来任务，包括功能、修复、数据工作、部署与运维。既有 OpenSpec artifacts 原地保留作为历史或在途上下文，但不再驱动流程。

## 流程总览

`探索 -> spec/design -> 方案审核 -> 用户确认实现 -> 测试先行 -> 子代理实现 -> 独立 reviewer 会话 /review -> 用户授权后发布`

任一阶段发现范围、风险或验收条件变化，都应回到对应的 spec/design 与测试用例更新；不得用实现结果反向替代需求确认。

## 1. 项目探索

- 先阅读 `AGENTS.md`、本文件以及 `docs/session_bootstrap.md` 指定的状态文档。
- 使用 Codex 原生只读能力检查代码、文档、当前分支、相关测试和必要的运行态证据。
- 需求不清、存在多条合理路径或属于高风险改动时，可以使用 `grill-me-codex` 一次只确认一个决策分支；用户已经明确的事项不得重复询问。
- 本阶段不得调用 `openspec-explore`，不得修改代码、提交或执行生产写入。

## 2. spec/design 编写

新任务在 `docs/changes/<slug>/` 建立以下持久产物：

- `spec.md`：范围、非目标、用户行为、验收标准和失败边界。
- `design.md`：现状、架构、数据流、状态与并发、迁移/回滚、性能与可观测性。
- `test_cases.md`：正常、边界、失败、回归、集成/运行态用例，以及 RED/GREEN 证据位置。
- `tasks.md`：使用 `(application)`、`(integration)`、`(operations)` 前缀，按测试、实现、验证顺序拆分。
- `rollout.md`：记录对既有任务/worktree 的影响、生效边界、安全检查点、恢复 handoff 与发布状态。

优先使用 Codex 原生规划能力编写；当前没有可用的通用 spec/design 原生 skill，不得因此回退到 `openspec-propose`。既有任务若已有 OpenSpec 规格，可以读取原 artifacts，并在 `docs/changes/<slug>/` 记录后续增量或明确以哪个既有文件为在途基线。

## 3. 方案审核

- 优先使用可用的 Codex 原生方案审核能力。
- 工作流进入本阶段且当前没有合适的 Codex 原生方案审核能力时，自动使用项目 `plan-eng-review`，无需用户再次点名；检查架构、数据流、数据库迁移、任务行为、测试覆盖、性能、部署安全和文档一致性。
- 同一需求首次方案审核建立 reviewer 会话；后续方案复审必须回到同一 reviewer、同一会话与上下文。只有原 reviewer 明确确认会话不可恢复时才允许新建，并记录原因、上轮 findings 与已知问题交接。
- 方案复审只核对上轮具体 findings、对应方案修复和直接触及路径。只有当前具体漏洞的直接 P0/P1 回归可以新增阻塞；其他新发现记录为后续建议并结束本轮方案审核，禁止扩成新的通用体系或无关加固。
- findings 必须先于结论，阻断项清零后才可进入测试与实现。

## 4. 用户确认实现

- 方案审核通过后，主代理必须汇报根因、最终修改范围与预计文件、测试用例和 RED 取得方式、历史数据处理边界、风险/非目标/回滚，以及方案 reviewer 结论，然后停止。
- 只有用户针对当前已审方案明确回复“确认实现”“开始实现”“继续实现”或同义语句，才可进入测试先行。最初任务描述、探索授权、规格编写授权和更早版本的实现授权均不得复用。
- 确认前禁止编写或修改自动化测试、修改应用代码/配置/迁移、启动实现 subagent、执行历史数据重处理、commit、push、创建 PR 或部署。

## 5. 测试先行

- 开发前补全 `test_cases.md`，并先实现对应自动化测试。
- 必须实际运行相关测试并记录 RED：失败应由目标行为尚未实现导致，而不是语法、fixture 或环境错误。
- 实现阶段按 GREEN、REFACTOR 推进，并保持新增测试与受影响回归测试通过。
- 只有不改变任何运行时行为的纯文档或纯配置整理，才可明确说明自动化 RED 不适用；仍必须记录并执行格式、解析、链接、静态或 render 验证。feature flag、队列/路由、权限、依赖、容器或部署顺序、数据行为等配置变化会改变运行时行为，必须测试先行，不得使用该豁免。

## 6. 子代理实现

- 所有实现工作必须委派给 subagent；按文件边界或领域拆成清晰任务，并明确禁止 commit、push、部署和生产写入。
- 静默规则覆盖所有 subagent，不限于实现：实现、测试、审核、调研或其他 subagent 中任意一个处于 active 时，直到全部 active subagent 结束，主代理只能继续派出新的 subagent，或等待/接收结果。此期间不得读/改文件、运行测试、继续调研、向其他任务发消息、处理用户追加的无关工作或执行其他工具调用。
- 写密集或文件有重叠的任务默认串行；仅当文件边界完全不重叠时才并行。
- 每个 subagent 必须返回：工作摘要、改动文件、执行的测试及结果、已知风险/未完成项。主代理等全部实现结束后再统一检查、整合与验证。

## 7. 独立审核与连续复审

- 同一需求的首次代码审核建立 reviewer 会话；后续复审必须回到同一 reviewer、同一会话与上下文。首次 reviewer 必须未参与实现，并实际调用 Codex 原生 review，而不是仅按 review 风格自行阅读 diff。
- 只有原 reviewer 明确确认会话不可恢复时才允许新建 reviewer；必须记录不可恢复原因、上轮 findings 与已知问题交接，不能用“方便”或“上下文太长”作为理由。
- 复审严格限定为上轮列出的具体漏洞/阻塞项、对应修复，以及这些修复直接触及路径的回归。不得把复审扩展成新的通用安全体系、发布协议或无关 P2/P3 加固。只有属于当前具体漏洞直接回归的 P0/P1 新问题才继续阻塞；其他新发现写成后续建议并结束本需求审核。

下列受检块是 CLI/subagent 的全部可执行 review 命令形态；任何 scope 都不得省略命令内 read-only override：

<!-- WORKFLOW_CONTRACT:REVIEW_COMMANDS:START -->
- `codex review -c 'sandbox_mode="read-only"' --uncommitted`
- `codex review -c 'sandbox_mode="read-only"' --base <base_oid>`
- `codex review -c 'sandbox_mode="read-only"' --commit <commit_oid>`
<!-- WORKFLOW_CONTRACT:REVIEW_COMMANDS:END -->

- 桌面/IDE 交互环境使用产品自身的只读 `/review`。CLI 或 subagent 环境的 uncommitted review 使用 `codex review -c 'sandbox_mode="read-only"' --uncommitted`；发布前尚未提交的改动统一使用此范围。branch/base 与 commit review 只允许完全 clean 的工作树：无 staged、unstaged、untracked，ignored 文件不计；否则 helper/reviewer fail closed，并要求改用 `--uncommitted` 或先建立经授权的提交。branch/base review 先执行只读 `git rev-parse --verify '<base-ref>^{commit}'` 得到不可变 `base_oid`，记录 `merge_base_oid`，tracked diff 严格固定为 `merge_base_oid -> HEAD`；先确认当前 Codex CLI 接受 `--base <sha>`，实际 review 只使用 `codex review -c 'sandbox_mode="read-only"' --base <base_oid>`，禁止把分支名等可移动 ref 交给 Codex。commit review 同理先把用户输入解析为 `commit_oid`，再只使用 `--commit <commit_oid>`。解析失败、工作树不 clean 或 OID 在审前核对中不一致即 `BLOCKED`。
- reviewer 在第一次 review 前只运行仓库跟踪的只读 helper，并保存完整原始 stdout 与总 hash 作为不可变基线；每次 review 尝试后立即再次运行同一命令：

  ```sh
  # uncommitted
  python3 .codex/scripts/review_fingerprint.py
  # branch/base，审前审后使用完全相同的不可变 OID
  python3 .codex/scripts/review_fingerprint.py --base <base_oid>
  # commit，审前审后使用完全相同的 commit OID
  python3 .codex/scripts/review_fingerprint.py --commit <commit_oid>
  ```

  禁止用 heredoc、shell 重定向、临时文件或复制到提示词中的内嵌实现替代 helper。命令必须退出 0，前后完整原始 stdout 与 `FINGERPRINT_SHA256` 必须逐字节一致；任何失败、变化或无法比较均为 `BLOCKED`，不得接受变化后的状态为新基线。
- helper 输出机器可比较的 `CANONICAL_PAYLOAD`/`FINGERPRINT_SHA256` 和可报告的 `SUMMARY`。每次 helper 调用至少连续构造两份完整快照；每份都重新读取 HEAD、`git status --porcelain=v2 --branch -z --untracked-files=all`、对应范围的 tracked binary diff、完整 untracked manifest，以及全部当前 tracked/untracked non-ignored leaf 的 Git 内容清单。内容清单按 path 排序并记录 Git mode/type/blob OID，删除项缺席；冲突、特殊类型和竞态 fail closed。helper 在任何 status/diff/hash 前检查 Git-visible 路径的 `filter` 属性；会触发外部 clean filter 的路径直接阻塞，且 blob identity 只用 `git hash-object --no-filters` 计算，绝不执行外部 filter。只有两份 canonical payload 完全相同才输出成功。base payload 记录 `base_input`、`base_oid`、`merge_base_oid` 和 `head_oid`；commit payload 记录 `commit_input` 与 `commit_oid`。base/commit 要求完全 clean；uncommitted 使用 `HEAD` 到工作树的 binary diff，并把 `summary.head` 与 `content_manifest_sha256` 作为 approved parent/content hash。
- untracked manifest 按路径排序，包含 Git 返回的普通 leaf 和其祖先目录。祖先目录只记录 `lstat` type/mode；regular leaf 使用 `O_NOFOLLOW` 打开，并复核仓库范围预扫描、打开前后 `lstat`/`fstat` 的 device、inode、type、mode、size、mtime_ns、ctime_ns 后记录内容 SHA-256；symlink leaf 只记录 link target，绝不跟随。若 Git 返回的 leaf 自身是 directory（典型为嵌套未跟踪 Git 仓库），helper 直接 fail closed，不递归、不跟随，并要求先显式纳入范围、移出父仓库或单独审核。特殊类型、Git 命令失败或 identity 漂移同样阻塞。所有 Git 子命令固定使用 `GIT_OPTIONAL_LOCKS=0`，helper 不写目标仓库。
- 审核结果必须记录实际命令或模式、审核范围、内层启动头、前后指纹、退出/完成状态和摘要，再按严重度列出 findings，包含文件和定位；无发现也要明确报告范围与残余风险。桌面/IDE 的 `/review` 没有进程退出码时，记录交互完成状态，并确认产品自身只读 reviewer 已完成；无法确认只读状态或完成状态时必须 `BLOCKED`。CLI 必须记录真实退出码，且内层启动头必须实际报告 `sandbox: read-only`；只设置外层 agent 的 `sandbox_mode` 不算满足。命令/交互 `completed`（CLI exit 0）只证明原生 review 执行成功，不等于审核门禁通过。
- reviewer 自身保持仓库 read-only，不得改变 diff 或使用永久 `danger-full-access`。CLI 首次仅因 Codex 状态库或网络的外层 sandbox 无法访问而失败时，只能对完全相同、已经包含 `-c 'sandbox_mode="read-only"'` 的命令申请 `require_escalated`/用户批准后重跑；提权只用于 Codex 状态库/网络，不得改变命令、审核范围、内层 sandbox 或目标 diff。升级重跑时必须再次核对内层启动头为 `sandbox: read-only`，并用同一初始指纹完成前后校验。批准被拒、无法申请、相同命令重跑仍失败、启动头不是 read-only 或指纹不一致时，审核门禁保持阻塞。
- “成功 review”必须同时满足：原生 review 覆盖完整目标范围；审核前后全部指纹原始输出完全一致；内层实际为 read-only；所有 P0-P3 finding，以及 reviewer 以任何等级标为 actionable 的 finding，均已清零。本项目不允许以用户接受风险替代 actionable finding 修复；可以报告非 actionable 的残余风险，但它们不得掩盖范围缺失。任一条件不满足时，结论只能是 `BLOCKED` 或 `REVISE`，不能进入发布授权门禁。
- 原生命令不可用、返回非零、被取消或未覆盖目标范围时，审核门禁保持阻塞并如实报告；普通 `git diff`、测试、lint 或人工检查只能作为补充证据，不得冒充原生 review 成功。
- 出现 actionable finding 后必须修复并回到同一 reviewer 会话复审。reviewer 只核对上轮 finding、对应修复及直接触及路径；满足连续复审边界并确认阻塞项清零后，findings 才算关闭。

## 8. 发布

<!-- WORKFLOW_CONTRACT:RELEASE_AUTHORIZATION:START -->
当前任务发布授权必须在最新一轮成功 review 之后取得。
<!-- WORKFLOW_CONTRACT:RELEASE_AUTHORIZATION:END -->

授权必须由用户针对当前任务明确说出“上线”“发布吧”或同义语句。`let's go` 只代表可以开始规划/实现，不是发布授权；其他任务中的授权、历史文档里的词和本任务较早轮次的授权均不得复用。授权前禁止：

- commit、push、merge、创建 PR；
- 部署、迁移、重启服务或生产数据写入；
- 任何会改变线上状态的操作。

### Review 内容冻结

发布门只要求三件事：最新成功 review、用户对当前任务的明确授权、实际发布内容未改变。
完整 fingerprint 用于确认第三项，不引入额外 receipt 或发布协议。

<!-- WORKFLOW_CONTRACT:FINGERPRINT_FREEZE:START -->
- 成功 review 记录受审 scope、完整 fingerprint、approved parent（审核时 HEAD）和 approved content hash（`content_manifest_sha256`），作为当前任务最新审核基线。
- 用户授权后、staging 前完整 fingerprint 必须用相同 scope 重算并与审核基线逐字节一致；不一致则停止。
- 显式 stage 全部受审改动后，允许 status/index 表示发生变化；但 HEAD 必须仍为 approved parent，且无 unstaged、untracked 或 conflict，index 的 `content_manifest_sha256` 必须与 approved content hash 一致。漏 stage、夹带或内容变化均停止。
- 任何实际内容差异都会使该轮 review 与授权失效；必须回到同一 reviewer 会话，仅复审变化、对应修复和直接触及路径，并在成功后重新取得当前任务授权。
<!-- WORKFLOW_CONTRACT:FINGERPRINT_FREEZE:END -->

staging 校验只验证受审内容保持，不建立额外发布协议：

```sh
python3 .codex/scripts/review_release_transition.py index \
  --approved-parent <approved_parent> \
  --approved-content-hash <content_manifest_sha256>
```

命令成功只证明 index 与审核内容一致；不替代 commit、push、部署各自原有的授权和验证。

### 部署后证据收尾

部署后必须按仓库要求回写真实状态，但这不应造成无限“改文档 -> review -> 重新授权 ->
重复部署”循环。当前任务的发布授权允许一次受限的 post-release evidence-only closure。
以下文件 allowlist 是精确全集：

<!-- WORKFLOW_CONTRACT:EVIDENCE_ALLOWLIST:START -->
- `docs/current_state.md`
- `docs/project_status.md`
- `docs/deploy_runbook.md`
- `docs/decisions.md（仅必要发布决策）`
- `docs/changes/<slug>/release_report.md`
<!-- WORKFLOW_CONTRACT:EVIDENCE_ALLOWLIST:END -->

`docs/decisions.md` 只允许追加发布时不可避免且已发生的必要决策，不得借机改变治理规则。
以下类别是 evidence-only 通道的精确禁入全集：

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

- allowlist 文件中只可追加已发生的 SHA/版本、备份、run id、计数、health、队列与 flags、
  回滚点和成功/失败/部分完成结果；不得夹带任何禁入类别的行为变化；
- 完成证据 patch 后复用同一需求既有代码 reviewer 会话，按第 7 节实际执行原生 review；
  如有纯证据范围内的修正，继续在该会话中按上轮具体 finding 复审；
- 证据 review 通过后，可在同一当前任务授权下 commit/push 证据文档并结束任务，不要求
  重复部署或再次索取授权；证据 commit 自身的 SHA 在最终回复、PR 或发布元数据中报告，
  不要求把该 SHA 再写回文档，因此不会生成递归 patch；
- reviewer 要求的修复若超出上述证据范围，或会改变任何行为性文件或治理规则，证据通道立即失效，
  回到完整 review freeze，并在成功 review 后重新取得当前任务授权。

必须始终区分本地验证、候选环境和生产运行态。若发布失败，证据收尾应如实记录失败、
已执行的回滚和剩余阻塞，不得把任务标记为成功。

## 既有在途任务迁移

- `2026-07-15` 切换时正在执行原子写入、长任务或共享维护窗口的任务，先完成当前原子操作并停在安全检查点，不得为了改流程中断到半事务状态。
- 从安全检查点起，读取既有 spec/design/tasks 作为基线；补齐或更新 `test_cases.md`，对尚未实现行为先写自动化测试并取得真实 RED，再交给实现 subagent，最后由该需求首次代码审核建立的 reviewer 会话实际执行原生 review。
- 已经实现的历史行为若当时没有保存 RED，不得事后构造失败记录；只为剩余或新变更行为取得真实 RED。已经完成且有证据的生产动作不得为了流程整齐而重做。
- 现行文档中曾写明“下一步运行旧 OpenSpec skill”的交接，自本流程生效起全部被本节取代；历史叙述可保留，但不再构成可执行指令。

## 禁用能力

以下 skills 不再用于 Umanews 工作：

- `openspec-explore`
- `openspec-propose`
- `openspec-apply-change`
- `openspec-archive-change`
- `openspec-sync-specs`

OpenSpec CLI、phase、journal 和 workflow-spine 不再是新流程门禁。`openspec/` 与 `openspec/config.yaml` 仅为历史/在途 artifacts 兼容保留。
