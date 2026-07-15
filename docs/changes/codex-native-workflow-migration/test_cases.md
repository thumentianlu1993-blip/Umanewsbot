# Codex 原生工作流迁移测试用例

## 规则静态验证

- `AGENTS.md`、`docs/codex_workflow.md`、`docs/session_bootstrap.md` 必须包含七阶段顺序、
  subagent 静默规则、方案/代码 reviewer 会话复用、具体漏洞复审范围、最新成功 review 后
  发布授权和 OpenSpec skills 禁用表。
- `docs/changes/codex-native-workflow-migration/` 必须包含五份 durable artifacts；`tasks.md` 的任务使用
  `(application)`、`(integration)`、`(operations)` 前缀并按测试、实现、验证排序。
- current state/status/decisions 明确本迁移尚未发布，且不把历史 OpenSpec 描述当现行指令。

## 归档完整性

- `archive/disabled-skills/2026-07-15/` 保留 OpenSpec 五 skills、旧 `grill-me`、旧
  `grill-me-codex`、OpenSpec 版 `plan-eng-review` 的 references/scripts 和 workflow-spine。
- 被禁用 skill 不再位于 `.codex/skills/` 的可发现根；活动 skills 只保留预期替代项。

## 配置和文档解析

- `.codex/agents/*.toml` 可被 Python `tomllib` 解析。
- `openspec/config.yaml` 可被 YAML parser 解析。
- 活动 `.codex/skills/*/SKILL.md` frontmatter 存在且字段可解析。
- `git diff --check` 无空白错误；不得产生 `__pycache__`/`.pyc`。

## Fingerprint helper 用例

- 同一状态输出确定；raw porcelain v2/status、tracked binary diff 与 untracked manifest 身份正确。
- 单次调用连续完成两份完整快照；canonical payload 不一致时 fail closed。
- 第一份快照读完一个文件后，另一 untracked 文件、tracked 内容或 status 范围变化时 fail closed。
- regular 内容/可执行位、symlink target、祖先目录 mode 变化会改变 fingerprint；特殊文件阻塞。
- rename porcelain v2 记录可解析；全部 Git 子命令使用 `GIT_OPTIONAL_LOCKS=0`。
- 为 tracked path 配置带可观测副作用的外部 clean filter 时，helper 必须在执行 filter 前
  fail closed，stdout 为空且副作用 marker 不存在；blob identity 使用 `--no-filters`。
- `--base` 记录输入、resolved base OID、merge-base OID并哈希对应 diff；`--commit` 记录输入和 commit OID。
- Git 返回的 untracked directory leaf（嵌套 repo）直接阻塞；普通祖先目录继续进入 manifest。
- `--base` 与 `--commit` 只接受完全 clean 的工作树；dirty tracked、staged、untracked
  任一存在均 fail closed，ignored 文件不计。base 的 tracked diff 严格为
  `merge-base -> HEAD`，不得包含工作树内容；scope 固定记录 `base_oid` 与
  `merge_base_oid`，后续命令只使用这些不可变 OID。
- 非 Git 目录、Git 命令失败、snapshot 全局竞态均 fail closed，失败时 stdout 为空。

## Workflow contract checker 用例

- stdlib-only 的 `.codex/scripts/check_workflow_contract.py --repo-root <path>` 只读检查七阶段、
  subagent 静默、原生只读 review/actionable 清零、最新 review 后当前任务授权、freeze 与
  evidence-only closure、行为性配置不得豁免 RED、在途迁移、active skill allowlist、归档
  14 文件固定 SHA/权限/非 symlink、agent TOML/frontmatter、legacy config 与 durable artifacts。
- mutation 测试分别删除静默规则、加入 forbidden active skill、篡改归档文件、放宽
  operations 行为配置 RED 豁免；每种 mutation 都必须非零退出且 stdout 不宣称通过。
- 在 canonical 文件追加反斜杠换行的裸 CLI 命令必须失败；每个出现都独立校验，不能由
  同文件其他安全示例蒙混。
- 将完整 fingerprint 的“全部”改为“部分”、加入 archive/state/OpenSpec/spec 路径排除，
  或移除发布前同 scope/helper 参数重算比较，必须失败。
- 从 `grill-me-codex` 的五份 artifact 交接或 `plan-eng-review` 的 `rollout.md` 输入发现中
  删除 rollout，必须失败。
- 正向基线必须同时包含：首次方案/代码审核各建立 reviewer 会话，后续复审复用各自原会话；
  原会话不可恢复时记录原因和交接；复审只核对上轮具体漏洞、修复及直接触及路径；仅该
  漏洞的直接 P0/P1 回归可以新增阻塞。
- mutation 把代码或方案复审改为“每轮全新 reviewer”、删除具体漏洞范围或放宽为完整范围
  复审时必须失败；checker 还必须扫描 canonical 文件，拒绝旧全新 reviewer 规则残留。
- 当前仓库检查通过；checker 不修改被检查仓库，也不依赖第三方包。
- checker 必须锁定 staging 过渡：成功 review 记录 approved parent/content hash；授权后 staging
  前完整 fingerprint 不变；显式 stage 后只允许 status/index 表示变化，并要求 HEAD、worktree
  clean 条件与 index content hash 全部一致。

## 原生 review 只读与范围指纹

- Codex review CLI 的只读配置帮助必须列出 `--base <BRANCH>`；用真实 40 位 SHA 执行参数解析 smoke，
  确认 CLI 接受 `--base <sha>` 后，实际 review 才可使用该 immutable OID。
- reviewer 的内层启动头必须报告 `sandbox: read-only`；审前/审后分别独立调用 helper，
  同一范围参数、完整 stdout 与 hash 逐字节相同。
- uncommitted 不要求 base；branch/base 不得把可移动 ref 交给 Codex；commit 必须记录解析后的 OID。
- directory leaf、任一 snapshot 不稳定、范围 OID/merge-base 漂移或原生 review 非零均阻塞。

## 真实 RED/GREEN 证据

### Helper 建立早期证据

- helper 首次引入时运行
  `PYTHONDONTWRITEBYTECODE=1 python3 .codex/scripts/test_review_fingerprint.py`，初始 7 项中
  6 项失败，exit `1`。
- rename porcelain v2 与 `GIT_OPTIONAL_LOCKS=0` 各自补测时均取得过后续真实 RED；现有
  交接没有保留足以逐字节引用的完整 stdout，因此这里只记录已知事实，不补造日志或时间。

### 第六轮：全局稳定快照、不可变范围与 directory leaf

新增测试先于 helper/规则实现写入，首次命令：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 .codex/scripts/test_review_fingerprint.py
```

真实结果：exit `1`；共 16 项，`1 failure + 6 errors`，即新增 7 项未满足、原有 9 项通过。
失败摘要为缺少 `build_stable_payload`、缺少 `review_scope`，以及嵌套 repo directory leaf
错误返回成功。实现全局 identity fence、双完整快照、scope/OID 和 directory leaf 阻塞后，
两次测试断言先后因错误信息过窄得到 exit `1`（分别 `2 failures`、`1 failure`）；只放宽为
匹配所有 snapshot fail-closed 消息，没有放宽目标行为。

最终同一命令真实结果：exit `0`；`Ran 16 tests`，`OK`。

### 最终静态与 scope smoke

- Codex review CLI 只读配置的 help smoke：exit `0`，帮助列出 `--base <BRANCH>` / `--commit <SHA>`。
- 以不可变 `d6d6f58b2b5b90301d8fa633a650df28379c09e7` 作为 base 的 help 参数解析 smoke：exit `0`，
  确认当前 CLI 参数解析接受真实 40 位 SHA；未启动实际 review。
- `python3 .codex/scripts/review_fingerprint.py --base d6d6f58b2b5b90301d8fa633a650df28379c09e7`：
  exit `0`，payload 中 input/resolved/merge-base 均为该 OID。
- `python3 .codex/scripts/review_fingerprint.py --commit d6d6f58b2b5b90301d8fa633a650df28379c09e7`：
  exit `0`，payload 记录 immutable commit OID。
- 连续两次 uncommitted helper 的 stdout shell 精确比较：exit `0`。
- agent TOML：5 份解析通过；OpenSpec YAML 与活动 skill frontmatter：3 份解析通过；
  archive 14 个原文件逐 blob hash 对账通过。
- Python AST、`git diff --check` 与 pycache 扫描通过；最终 freeze 前仍须在最后一次文档更新后重跑。

### 第七轮：committed scope clean-tree 与 workflow contract checker

先更新本文件并新增/修改自动测试，再在实现前运行：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 .codex/scripts/test_review_fingerprint.py
PYTHONDONTWRITEBYTECODE=1 python3 .codex/scripts/test_workflow_contract.py
```

真实 RED：fingerprint exit `1`，`Ran 20 tests`，`6 failures + 1 error`；dirty tracked、
staged、untracked 在 base/commit 下均错误返回成功，且 scope 缺少 `base_oid`。contract
checker exit `1`，`Ran 5 tests`，`5 failures`，原因是 checker 尚不存在；四类 mutation
也因此没有得到预期的具体 fail-closed 错误。

实现 clean-tree committed scope、`merge_base_oid -> head_oid` diff、固定 archive contract
和 stdlib-only checker 后，同一组命令真实 GREEN：fingerprint exit `0`，`Ran 20 tests`，
`OK`；workflow contract exit `0`，`Ran 5 tests`，`OK`。随后执行
`python3 .codex/scripts/check_workflow_contract.py --repo-root .`，exit `0` 并输出
`WORKFLOW_CONTRACT_OK`。

### 第八轮：受检语义块、发布顺序与数量一致性

先新增 review 命令、发布授权顺序、freeze、evidence-only allowlist 和数量一致性 mutation，
实现前运行 workflow contract tests。真实 RED：exit `1`，`Ran 10 tests`，`5 failures`；
现有 checker 会放过移除 read-only override，且 canonical 文档尚无可供 mutation 定位的授权、
allowlist、freeze 与五份 artifact 稳定块。

实现受检块与精确集合校验、禁止无 override 的可执行 review 命令、自动统计测试 inventory，
并统一文档口径后，同一命令真实 GREEN：workflow contract tests `10/10`，exit `0`，
`Ran 10 tests`，`OK`。fingerprint tests 未新增，保持 `20/20`，exit `0`。

### 第九轮：跨行命令、动态完整 fingerprint freeze 与 rollout skill

先新增七个 mutation tests，覆盖反斜杠续行裸 CLI、完整 scope 的“全部”语义、archive/state
和 OpenSpec/spec 排除、发布前同参数重算，以及两个 skill 的 rollout 交接。实现前真实 RED：
exit `1`，`Ran 17 tests`，`7 failures`；旧 checker 会让这七种 mutation 全部通过。

实现跨行空白规范化逐项命令校验、受检完整 fingerprint freeze、排除语句阻断、release
preflight 比较和 rollout skill 输入后，同一命令真实 GREEN：workflow contract tests `17/17`，
exit `0`，`Ran 17 tests`，`OK`。fingerprint tests 未新增，保持 `20/20`。

## Bootstrap 边界

本迁移开始时新流程和本目录尚不存在，用户直接要求立即建立规则；最早治理文档编辑没有、
也不可能以前置本目录为门禁，不得伪称已经执行。上述 helper RED/GREEN 是目录建立后真实
发生的测试先行证据。

### 第十一轮：受检 Git 表示转换（历史测试资产）

- fingerprint payload 必须给出 approved parent、完整 fingerprint 与所有 Git 可见 leaf 的
  content manifest/hash；冲突、特殊类型和不稳定快照 fail closed。
- transition verifier 的现行工作流用途仅为 index 校验：正向覆盖 staging 全部受审改动，负向
  覆盖 stage 夹带/遗漏、批准后内容变化、unstaged/untracked、错误 approved parent。既有 commit/
  remote 用例是历史测试资产，不是现行发布门禁，也不建立 receipt/CAS/push 协议。
- shell mutation `codex re\\` + newline + `view --uncommitted` 必须按 shell 续行语义拼成裸
  `codex` 的 `review` 命令并失败；删除 transition 规则或放宽 content hash 逐字节相等也必须失败。
- 本轮先写测试的真实 RED：fingerprint exit `1`（22 项中 2 errors）；transition exit `1`
  （9 项均因缺少 content manifest error）；workflow exit `1`。实现后的最终计数由 checker
  从测试 AST 读取并同步到 current state/project status/本文件。

实现后的真实 GREEN：fingerprint `23/23`、transition `9/9`、workflow contract tests `21/21`（20 mutations + 1 baseline）；另验证 helper 计算 blob OID 不增加目标仓库 object count。该行是第四轮当时快照，不是当前总数。

### 审核会话复用与范围收敛

- 先把代码/方案复审复用规则与旧规则拒绝 mutation 写入测试；在 canonical 文档尚残留
  “每轮全新 reviewer”且 checker 仍要求已移除的发布加固标记时，真实 RED 为 exit `1`，
  `Ran 23 tests`，`16 failures`。
- 本轮实现目标不是继续加强发布协议，而是让 checker 锁定四项最小契约：代码复审复用、
  方案复审复用、不可恢复时记录原因与交接、复审只限上轮具体漏洞/修复/直接触及路径，
  且仅直接 P0/P1 回归可新增阻塞。
- 统一 reviewer 规则与 checker 后真实 GREEN：workflow contract tests `25/25`。
- 发布验收保持“最新成功 review + 当前任务用户明确授权 + 内容未变”；不把额外 receipt、
  receipt-only transition 或特定 push 协议作为本工作流的现行必需项。

### 代码 reviewer 三项 finding 修复

- 外部 filter 新测试先取得真实 RED：目标单测 exit `1`，helper 错误返回 `0`；修复后 helper
  在 filter 执行前阻塞，副作用 marker 不存在。
- staging 契约新测试先取得真实 RED：目标单测 exit `1`，缺少 `staging 前完整 fingerprint`
  等语义；临时 Git repo 的完整 staging/index 正向用例在旧 verifier 上已为 GREEN，因此不伪造
  该用例 RED。漏 stage、夹带、内容变化的既有负向用例继续保留。
- 实现后精确总数：fingerprint `24/24`、transition/index `10/10`、workflow contract tests `26/26`；
  本行仅在三组测试和 checker 实际 GREEN 后成立。
