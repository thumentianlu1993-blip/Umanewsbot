# Rollout 与安全检查点

## 当前边界

- 工作目录：`/Users/mentianlu/.codex/worktrees/resumable-graded-top5/umanews`
- 基线：远端 `research/2026-graded-top5-wikipedia` 的 `3a6a61fb...`
- 2026-07-27 preflight：`origin/main=a59956b327157d29630fab1f1c98ba9c9cacfed0`，
  research 相对 main 为 ahead 7 / behind 4；双方 changed-file overlap 为 0。
- PR：#24，草稿，base=`main`
- 原 `/Users/mentianlu/Code/umanews` 工作树包含其他会话改动，不在本任务写入范围。
- 本任务不是生产部署，不登录或修改 `/opt/umanewsbot`。

## 2026-07-27 实现检查点

- 已在限定 worktree 完成分阶段 collector、StageStore、原子 checkpoint、稳定分片、全覆盖
  merge、错误状态、纯离线 finalize 和 11-job artifact DAG。
- 聚焦离线测试由真实 `14 tests / 3 failures / 10 errors` RED 收敛为
  `21 tests / OK`；`py_compile`、YAML 静态解析和 `git diff --check` 通过。
- workflow 的 PR 与默认手工输入只执行离线 tests/sample；所有公网 job 都要求显式
  `workflow_dispatch` 且 `full_network=true`。本轮没有触发该输入。
- 当前仍停在独立 code review 前；未 commit、push、更新 PR、运行完整公网采集、部署或写生产。

## 2026-07-27 首次 code review 返修检查点

- 首次 reviewer 会话 `019f9f89-876b-7531-a685-fcd5767d7cee` 为 `REVISE`；返修未新建 reviewer
  会话，完成后必须回到该会话。
- workflow 已去除 attempt 通配和 `merge-multiple`，只接受当前精确 attempt 或显式唯一
  `source_run_id + source_attempt`；缺一和 manifest/index 不兼容均拒绝。
- tests job 现在真实产生 safe-stop 75 checkpoint，恢复后执行 profile/search/entity/score
  fan-in 与纯离线 finalize，并上传 stage tree、final、safe-stop 与字节等价报告。
- 限定复审 P1 已修复：真实 races/profile/search/entity/score job 不再把 `75` 视为成功；job
  failure 阻止 `needs` 下游，`if: always()` 仍上传 checkpoint。只有后续恢复返回 `0` 才继续 DAG。
- 每个 index 绑定 manifest SHA、全部具名上游 index SHA、计划输入 digest、tool identity 与实际
  request count；manifest 加载重算 race URL digest 并核对 schema/parser/scorer/base commit/tool。
- profile detail 失败不再被空 profile 覆盖；finalize 汇总全部阶段结构化错误并聚合各网络阶段
  request count。
- 返修聚焦测试由 `26 tests / 2 failures + 4 errors` RED 收敛到 `27 tests / OK`。未运行公网采集，
  未 commit、push、更新 PR、部署或写生产；下一步仅为原 reviewer 会话复审。

## 2026-07-27 正式 run 续跑失败检查点

- 源 run `30241479829` 已完成 races/profiles/merge_profiles；其 search shard `0/1/3` 以
  safe-stop `75` 结束，shard `2` 完成。失败阶段之后没有 entities/score/finalize artifact。
- 恢复 run `30246234850` 提供精确 source run/attempt，但 workflow 从 races 开始重跑。已完成
  races 中仍有 retryable failures，runner 将其重试并重建 index，使 SHA 从 `b8bb…` 变为
  `4734…`；四个 profiles shard 均因绑定旧 races SHA 而报 `stage upstream index drift`。
- 根因是恢复合同只锁定 source attempt，没有锁定 source stage；同时 runner 把 item
  `retryable_error` 误当成任何 resume 都应重试，未区分“完整 stage 中保留的错误”和
  “safe-stopped stage 待继续的错误”。
- 本轮仅新增规格与离线 RED：聚焦测试 `Ran 30 tests`、`failures=2`，分别命中完成 races 被
  重跑和 workflow 缺 `source_stage`；safe-stopped shard 继续用例通过。未修改实现、workflow
  或 README，未调用 GitHub、联网、commit、push、部署或写生产。
- GREEN 实现已收敛为 `Ran 30 tests / OK`：完成 stage/shard 只有在 index/item/progress/
  planned coverage 全部验证且 `safe_stopped=false && processed==total` 时才字节级 no-op；
  safe-stopped shard 仍可续跑。workflow 已加入 source 三元组和精确 stage 前缀下载，README
  已记录恢复命令。编译、YAML `11` jobs、静态合同和 diff check 通过；仍未联网或发布。

## 2026-07-28 reviewer 019fa715 P1 边界

- `0cdec…` 旧 collector 产生的正式 run artifacts 与修复提交的 base commit/source SHA 不兼容。
  既定 rollout 不做旧 checkpoint 迁移：旧 artifacts 只保留为 evidence，修复提交发布后的首个
  研究 run 必须三项 source 输入全空并 fresh start。
- 后续恢复仅允许相同新 HEAD、`collector_source_sha256` 和完整 tool identity 的 runs；即使
  workflow source selector 精确，跨提交恢复仍由 manifest 校验 fail closed。
- reviewer 还指出 periodic index 与 progress 之间存在合法崩溃窗口。本轮先新增 RED：仅允许
  已验证 index 严格领先 safe-stopped progress，或 progress 缺失且 index 为严格 partial coverage
  时按 safe-stopped 继续；同覆盖 hash 错误仍拒绝，未知状态不得当成 completed。
- 聚焦 RED 为 `Ran 32 tests / errors=2`：分别是 `stage progress index drift` 和
  `stage progress missing for resume`；其余 30 项通过，包括 base commit/collector source 漂移
  拒绝和同覆盖错误 hash fail closed。本检查点未修改实现、workflow 或 README。
- P1 GREEN 后为 `Ran 32 tests / OK`。collector 只协调 verified index 严格领先 safe-stopped
  progress，以及 progress 缺失的严格 partial index；当前 index items/request count 为权威，
  完整 index 缺 progress、同覆盖 hash 错和所有 identity/input/item 漂移继续 fail closed。
  README 已写明 `0cdec…` evidence-only 与新提交 fresh start；workflow 无需继续扩展。

## 安全检查点

1. 方案 review APPROVED。
2. RED 前 fetch 并记录最新 `origin/main`，复核重叠后安全整合；如方案内容变化，回同一 reviewer。
3. 新增测试真实 RED，失败只因目标能力缺失。
4. 实现 subagent 完成 GREEN；不得 commit、push、部署或联网跑全量。
5. 主代理复验离线测试、小样本和中断恢复。
6. 未参与实现的 reviewer 只读审查；findings 修复后复用同一 reviewer。
7. review 通过后冻结 fingerprint。
8. commit/push/更新 draft PR 与触发 GitHub Actions 属于发布动作，等待最新 review 后的当前版本授权。
9. 首次 GitHub run 只跑小样本/fixture artifact 链。
10. 完整网络研究 run 需单独确认，且仍只在 GitHub/研究环境运行。

## GitHub Actions 失败处理

- matrix `fail-fast: false`；每个 job 在 timeout 至少 10 分钟前由脚本预算安全停止、保存
  stage+shard checkpoint，并上传绑定 run/attempt/stage/shard 的独立 artifact。
- 一个 shard 失败时保留其他 shard；不得用新提交取消正在完成的长任务。
- 第二 attempt 只为安全停止 shard 选择 manifest/tool/input SHA 全兼容的最新 checkpoint；
  已完成 shard 完整校验后字节级 no-op，不重试其 retryable errors、不重写 index/progress。
  v4 artifact 不同名覆盖。
- 跨 run dispatch 必须提供 `source_run_id + source_attempt + source_stage` 三元组；
  `source_stage` 之后的源 artifact 一律不下载。源阶段之前的完成 stage 只验证并复用，源阶段
  内仅 `safe_stopped=true` 的 shard 继续。
- merge job 只下载明确 artifact，缺 shard 或冲突则 fail closed。
- DAG 固定为 profiles merge、search merge、entities merge、horse scoring merge 后再 finalize；
  finalize 不直接读取单个 entity/search shard。
- workflow rerun 优先复用同一 run 内的上游 artifact；跨 run 续跑必须显式指定 source run，
  未实现前不得声称自动跨 run 恢复。

## 回滚

本轮不涉及数据库和生产运行态。代码回滚是把研究分支恢复到 PR #24 基线；checkpoint 使用版本化
manifest，旧工具不覆盖新格式。若新 workflow 无法形成阶段 artifact，保持 PR 为草稿并恢复单纯
离线测试，不运行单体三小时任务。

## 状态回写

实现和 review 完成后更新：

- `docs/current_state.md`
- `docs/project_status.md`

只有产生新的长期治理/产品链路/部署事实时才改 `docs/decisions.md`、
`docs/project_overview.md` 或 `docs/deploy_runbook.md`。本研究改造默认不满足这些条件。
