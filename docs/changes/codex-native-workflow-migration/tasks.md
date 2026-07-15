# Codex 原生工作流迁移任务

## 测试

- [x] (integration) 定义治理规则、skill 归档、配置解析与 durable artifacts 静态验收。
- [x] (application) 为 review fingerprint helper 补充确定性、竞态、scope/OID、rename、
  optional locks、文件类型与 directory leaf 测试。
- [x] (application) 为 base/commit clean-tree 门禁和 workflow contract checker 先补测试，
  分别覆盖 dirty tracked/staged/untracked 与四类 contract mutation，并取得真实 RED。
- [x] (application) 在实现 helper 强化前运行新增测试并记录真实 RED。
- [x] (integration) 第八轮为 read-only review 命令、review 后授权、当时的 freeze/evidence
  集合与数量一致性补 mutation tests，取得 `10 tests / 5 failures` 的历史真实 RED。
- [x] (integration) 第三轮方案审核后先补跨行 unsafe review、完整 fingerprint freeze、路径排除、
  release preflight 和 rollout skill mutation tests；实现前真实 RED 为 `17 tests / 7 failures`。
- [x] (application) 第四轮方案审核先补 Git 可见 content manifest、冲突 fail-closed 和完整
  uncommitted -> stage -> commit -> local bare remote push transition 测试，并保存真实 RED。
- [x] (integration) 第四轮先补 shell `re\\<newline>view`、删除 transition 规则与放宽 content
  hash 比较 mutation，再实现 checker 防护。
- [x] (integration) 为方案/代码 reviewer 会话复用、不可恢复交接、具体漏洞复审范围和旧
  “每轮全新 reviewer”规则拒绝补 contract mutation，并取得 `23 tests / 16 failures` RED。
- [x] (application) 为外部 clean filter 副作用阻断补目标单测并取得 helper 错误返回成功的 RED。
- [x] (integration) 为 review 后 staging 内容保持补 workflow contract RED，并新增临时 Git repo
  正向 index 用例；沿用漏 stage、夹带、内容变化负向用例。

## 实现

- [x] (application) 将探索、spec/design、方案审核、TDD、subagent 实现、新 reviewer 与发布授权
  七阶段规则写入 `AGENTS.md` 和 `docs/codex_workflow.md`。
- [x] (application) 重建 `grill-me-codex`、`plan-eng-review` fallback 与 `tdd`，软删除并完整
  归档不用的 skills/workflow-spine。
- [x] (integration) 配置 application/integration/operations/reviewer agents，并固化任意
  subagent active 时主代理静默的边界。
- [x] (application) 实现 helper 的双完整稳定快照、全局 identity fence、immutable base/commit
  scope 与未跟踪 directory leaf fail-closed。
- [x] (application) 收紧 base/commit 为 clean-tree committed scope，并实现 stdlib-only
  workflow contract checker、固定归档 SHA/权限和 active skill allowlist。
- [x] (operations) 同步 current state、project status、decisions 与 session bootstrap；明确
  既有任务迁移、安全检查点和 evidence-only 发布收尾。
- [x] (operations) 新增 `rollout.md`，逐项记录已知 task/worktree 的迁移状态与验收方式；
  其他在途 worktree 不批量改写，只在 resume/safe checkpoint handoff 时迁移。
- [x] (operations) 记录本迁移的 bootstrap 例外：最早编辑发生时本目录/新流程尚不存在，
  不伪造前置流程或历史 RED。
- [x] (integration) 建立定位到 canonical block 的语义 checker，统一五份 artifacts、fingerprint
  `20/20`、workflow contract `18/18` 口径，并记录 34 条 worktree inventory。
- [x] (integration) checker 对 canonical 文件的全部小写 CLI 命令做跨行规范化逐项校验，
  以完整 fingerprint 动态 freeze 替换不完整路径全集，并校验发布前同参数重算。
- [x] (application) `grill-me-codex` 明确交接五份 artifacts；`plan-eng-review` 自动读取
  `rollout.md`，缺失时产生 finding。
- [x] (integration) reviewer agent 改用动态完整 fingerprint freeze，并新增第 18 项 mutation
  锁定完整输出/hash、发布前同参数重算、无路径排除和部署后唯一例外。
- [x] (application) fingerprint helper 输出 approved parent/content manifest hash；新增只读
  transition verifier，逐段验证 index、普通单父 commit/tree 与权威 remote ref OID。
- [x] (application) 方案/代码首次审核各建立 reviewer 会话，复审复用各自原会话；统一限制
  为上轮具体漏洞、对应修复和直接触及路径，仅直接 P0/P1 回归可新增阻塞。
- [x] (integration) 发布门收敛为最新成功 review、当前任务用户明确授权和内容未变，删除
  receipt-only/CAS 等非七阶段必需门禁。
- [x] (application) fingerprint helper 在 status/diff/hash 前拒绝外部 filter path，并用
  `git hash-object --no-filters` 计算 blob identity，确保不执行 clean filter。
- [x] (integration) 发布冻结允许显式 staging 的 status/index 表示变化；staging 前完整
  fingerprint 不变，stage 后只读 verifier 校验 approved parent、clean 条件与 content hash。

## 验证

- [x] (application) 运行 helper 全部自动测试并确认 GREEN。
- [x] (integration) 运行 workflow contract mutation tests 与当前仓库 checker并确认 GREEN。
- [x] (integration) 连续运行 helper、base/commit scope smoke、Codex `--base <sha>` 参数解析 smoke。
- [x] (integration) 解析全部 agent TOML、OpenSpec YAML 与活动 skill frontmatter，检查归档完整性。
- [x] (operations) 运行 `git diff --check`，确认没有 pycache、commit、push、部署或生产写入。
- [x] (integration) 本需求原方案 reviewer 已按限定范围复审并返回 `APPROVED`。
- [ ] (integration) 代码 reviewer 当前仍为 `REVISE`；三项 actionable finding 候选修复完成后，
  回到同一代码 reviewer 会话，仅复审这三项修复与直接触及路径。
- [ ] (operations) 仅在最新成功 review 后等待用户针对当前任务明确发布授权。
