# Codex 原生工作流迁移 rollout

## 生效边界

本文件记录已知 Codex task/worktree 的迁移机制，不把本地编辑夸大为共享项目事实。当前
`codex-native-workflow-migration` task 已采用新七阶段规则，但本变更仍尚未发布。未来任务
只有在本变更成功 review、用户针对当前任务明确发布授权、提交并合入共享 `main` 后，才从
共享仓库 durable 生效；在此之前仅本迁移 worktree 直接受本地规则约束。

不批量修改其他现有 worktree 的 tracked `AGENTS.md`、skills 或治理文档：它们可能包含
在途 diff、原子数据操作或共享维护窗口，直接覆写会破坏上下文。迁移统一通过安全检查点
handoff、rebase 或同步最新 main 完成，并显式重读 `AGENTS.md`、`docs/codex_workflow.md`
与 `docs/session_bootstrap.md`。

## 动态 task snapshot

观察窗口截至 `2026-07-15T17:38:39+08:00`。本轮尝试调用 Codex task connector 的
`list_threads(limit=100)`；调用等待约 90 秒仍无 payload，随后终止。因此以下六个 ID 只
保留用户已知名称和路径名称关联，当前状态一律写 `unknown`，不复用旧文档中的
`active`、`paused` 或 `notLoaded` 作为当前事实，也不主动唤醒：

| task/thread | 关联 worktree（仅名称关联，connector 未确认） | 当前状态 | 观察时间/来源 | 恢复 handoff |
| --- | --- | --- | --- | --- |
| 历史抓取 `019f482d-df62-75c0-89d5-e359c185f06a` | `backfill-races-1984-release` / `historical-progress-guard` | unknown | `2026-07-15T17:38:39+08:00`；`list_threads` 未返回 | 恢复前先停在安全检查点，带 IDs/结果/SHA；重读 main 规则和显式消息，检查旧 skills，再 rebase/merge 或复制规则 |
| France `019f1717-0eed-77f1-8137-2bf977bfab38` | 主工作区 `codex/deploy-news-gates-france` | unknown | 同上 | 恢复前先停在安全检查点并交接运行态；重读 main 规则和显式消息，检查旧 skills，再 rebase/merge 或复制规则 |
| 新闻评估 `019f5c49-f7a1-7f02-b7c6-62f10b1eae03` | `news-quality-review-20260713` | unknown | 同上 | 恢复前冻结审核分母/证据；重读 main 规则和显式消息，检查旧 skills，再 rebase/merge 或复制规则 |
| P0 `019f481e-4133-7f43-9844-e7a59b33ba9a` | `p0-horse-info-completion` | unknown | 同上 | 恢复前交接完成态/identity conflict；重读 main 规则和显式消息，检查旧 skills，再 rebase/merge 或复制规则 |
| 海外候选 `019f3cf5-3129-76a3-8f8d-8a26ec557044` | `audit-overseas-candidate-pool` | unknown | 同上 | 恢复前冻结原始候选证据；重读 main 规则和显式消息，检查旧 skills，再 rebase/merge 或复制规则 |
| 长期术语 `019f3a78-d1e4-7a52-a467-4d703254bb48` | `fix-english-term-context-gates-release` | unknown | 同上 | 恢复前交接词表/门禁证据；重读 main 规则和显式消息，检查旧 skills，再 rebase/merge 或复制规则 |

## Worktree inventory snapshot

以下 34 行来自同一轮只读 `git worktree list --porcelain`，执行时间
`2026-07-15T17:38:39+08:00`。`状态` 仅写该命令直接提供的结构状态或本迁移 worktree
自身已知事实；connector 未确认的 task 运行状态均为 `unknown`。

<!-- WORKFLOW_CONTRACT:WORKTREE_INVENTORY:START -->
| worktree path | HEAD | branch/detached/prunable | 关联 task | 状态 | 安全检查点 / 恢复 handoff |
| --- | --- | --- | --- | --- | --- |
| `/Users/mentianlu/Code/umanews` | `dc6e43498e1eb7678feba5068bf0452c2623b24e` | `codex/deploy-news-gates-france` | France（名称关联） | unknown | 先停在生产安全点并交接运行态；重读 main/显式消息、查旧 skills，再 rebase/merge 或复制规则 |
| `/private/tmp/umanews-global-racing-capability` | `fe1016903db4c1b08e8a9bee4be71bd777ed9673` | `codex/global-racing-capability`; prunable，gitdir 不存在 | global racing capability（名称关联） | prunable；task unknown | 不改写；恢复先核验 path/gitdir 与安全点，再重读 main/显式消息、查旧 skills，并决定修复 worktree 或从分支重建 |
| `/Users/mentianlu/.codex/worktrees/0edc/umanews` | `0bd328148daa66cf49daa7033ffe64c02f00d10d` | `codex/record-external-horse-alias-deploy` | external horse alias deploy（名称关联） | unknown | 先停在发布安全点；重读 main/显式消息、查旧 skills，再 rebase/merge 或复制规则 |
| `/Users/mentianlu/.codex/worktrees/1ec6/umanews` | `2f0c35cac6e6d5b3b4c5250b154bc7eb3075c6d1` | detached | unknown | unknown | 恢复先确认 detached HEAD 所属 task/分支并停安全点；重读 main/显式消息、查旧 skills，再选分支同步规则 |
| `/Users/mentianlu/.codex/worktrees/9f43/umanews` | `62a6a027e44bdfddcf8b3fa18807dc9007b4b223` | detached | unknown | unknown | 恢复先确认 detached HEAD 所属 task/分支并停安全点；重读 main/显式消息、查旧 skills，再选分支同步规则 |
| `/Users/mentianlu/.codex/worktrees/audit-overseas-candidate-pool/umanews` | `de4bb78e7a1bb8e2fb634853b6cbbd9790d37713` | `codex/audit-overseas-candidate-pool` | 海外候选（名称关联） | unknown | 冻结候选证据后停点；重读 main/显式消息、查旧 skills，再 rebase/merge 或复制规则 |
| `/Users/mentianlu/.codex/worktrees/backfill-races-1984-release/umanews` | `06ac0c051b52a0e72ce1eb2335df10ae1bec7f8b` | `codex/backfill-races-1984-release` | 历史抓取（名称关联） | unknown | 原子批次完成后停点并交接 IDs/计数/SHA；重读 main/显式消息、查旧 skills，再 rebase/merge 或复制规则 |
| `/Users/mentianlu/.codex/worktrees/d081/umanews` | `6b3e2e45d0995ab479799e95259d17adfb12d6fd` | detached | unknown | unknown | 恢复先确认 detached HEAD 所属 task/分支并停安全点；重读 main/显式消息、查旧 skills，再选分支同步规则 |
| `/Users/mentianlu/.codex/worktrees/e2e6/umanews` | `62a6a027e44bdfddcf8b3fa18807dc9007b4b223` | detached | unknown | unknown | 恢复先确认 detached HEAD 所属 task/分支并停安全点；重读 main/显式消息、查旧 skills，再选分支同步规则 |
| `/Users/mentianlu/.codex/worktrees/f150/umanews` | `62a6a027e44bdfddcf8b3fa18807dc9007b4b223` | detached | unknown | unknown | 恢复先确认 detached HEAD 所属 task/分支并停安全点；重读 main/显式消息、查旧 skills，再选分支同步规则 |
| `/Users/mentianlu/.codex/worktrees/fix-english-term-context-gates-release/umanews` | `75b93f73a81dac5e2abe0b001f830e8eef3dc630` | `codex/fix-english-term-context-gates-release` | 长期术语（名称关联） | unknown | 冻结词表/门禁证据后停点；重读 main/显式消息、查旧 skills，再 rebase/merge 或复制规则 |
| `/Users/mentianlu/.codex/worktrees/guard-qqbot-offline/umanews` | `adfb3bacfd35d392c5859eb7336e61960a2e960a` | `codex/guard-qqbot-offline` | QQ bot offline guard（名称关联） | unknown | 停在无队列/发送写入安全点；重读 main/显式消息、查旧 skills，再 rebase/merge 或复制规则 |
| `/Users/mentianlu/.codex/worktrees/hkjc-ja-alias-article-backfill/umanews` | `538011e3c487ab3b9414ca4670eacc6a371ebb38` | `codex/codify-termbase-production-import-workflow` | HKJC alias / termbase import（名称关联） | unknown | 原子导入结束后交接 run/计数/SHA；重读 main/显式消息、查旧 skills，再 rebase/merge 或复制规则 |
| `/Users/mentianlu/.codex/worktrees/import-graded-races-2020-2026/umanews` | `18c24b92acdc36f316aa9f857b1e0e9890370ab0` | `codex/import-graded-races-2020-2026` | graded races import（名称关联） | unknown | 原子导入结束后交接 IDs/计数；重读 main/显式消息、查旧 skills，再 rebase/merge 或复制规则 |
| `/Users/mentianlu/.codex/worktrees/international-racing-coverage/umanews` | `4d09d25ced887db0025705f7143fda830e7bc266` | `codex/expand-international-racing-coverage` | international coverage（名称关联） | unknown | 停在数据/生产安全点并交接 scope；重读 main/显式消息、查旧 skills，再 rebase/merge 或复制规则 |
| `/Users/mentianlu/.codex/worktrees/mobile-density-polish/umanews` | `27169e8947675e1f2be7f63fb4d4995339be10c3` | `codex/record-mobile-density-deploy` | mobile density deploy（名称关联） | unknown | 停在发布验收点并交接 SHA；重读 main/显式消息、查旧 skills，再 rebase/merge 或复制规则 |
| `/Users/mentianlu/.codex/worktrees/mobile-h5-info-feed/umanews` | `1c9be7df83bb7e3380227b5ecb9b8a87be59dc9b` | `codex/mobile-h5-info-feed` | mobile H5 feed（名称关联） | unknown | 停在可复现测试点；重读 main/显式消息、查旧 skills，再 rebase/merge 或复制规则 |
| `/Users/mentianlu/.codex/worktrees/multiregion-news-production/umanews` | `538a1a9d5e407993a04acd3a5a9471add56192de` | `codex/increase-multiregion-news-volume` | multiregion production（名称关联） | unknown | 停在 flags/队列安全点并交接 run；重读 main/显式消息、查旧 skills，再 rebase/merge 或复制规则 |
| `/Users/mentianlu/.codex/worktrees/news-placeholder-hotfix/umanews` | `e3efd87928b9182a66046d12ce29f57478d2d900` | `codex/news-placeholder-hotfix` | placeholder hotfix（名称关联） | unknown | 停在翻译队列排空/门禁安全点；重读 main/显式消息、查旧 skills，再 rebase/merge 或复制规则 |
| `/Users/mentianlu/.codex/worktrees/news-quality-review-20260713/umanews` | `9d6dec34a33a0be872a8f62bb0f44e1dbff4b591` | `codex/news-quality-review-20260713` | 新闻评估（名称关联） | unknown | 冻结审核分母/证据后停点；重读 main/显式消息、查旧 skills，再 rebase/merge 或复制规则 |
| `/Users/mentianlu/.codex/worktrees/openspec-ready-20260626/umanews` | `9ff667af7cc1fe4c041713d8e387cef01ef67680` | `codex/start-hkjc-global-spikes` | HKJC global spikes（名称关联） | unknown | 停在网络/数据安全点；重读 main/显式消息并检查旧 OpenSpec skills，再 rebase/merge 或复制新规则 |
| `/Users/mentianlu/.codex/worktrees/p0-horse-info-completion/umanews` | `e123390fd4a569c6554fed8bfe206ca8592209db` | `codex/p0-horse-info-completion` | P0（名称关联） | unknown | 交接 completeness/identity conflict 后停点；重读 main/显式消息、查旧 skills，再 rebase/merge 或复制规则 |
| `/Users/mentianlu/.codex/worktrees/propose-multiregion-volume-windows` | `4323d3275bfd0456dededc1b7de0a3b599a1e482` | `codex/propose-multiregion-volume-windows` | multiregion windows（名称关联） | unknown | 停在方案边界；重读 main/显式消息并检查旧 propose skill，再 rebase/merge 或复制新规则 |
| `/Users/mentianlu/.codex/worktrees/qqbot-auto-push/umanews` | `c9e95be31e7f7163fe51d3390b3f5b61aebcbbc0` | `codex/archive-netkeiba-horse-data-import` | netkeiba import archive（名称关联） | unknown | 停在发送/导入安全点并交接计数；重读 main/显式消息、查旧 skills，再 rebase/merge 或复制规则 |
| `/Users/mentianlu/.codex/worktrees/race-detail-page/umanews` | `d78fab073577a9c0d09465f4b2edf92408542f11` | `codex/race-detail-page` | race detail page（名称关联） | unknown | 停在可复现测试点；重读 main/显式消息、查旧 skills，再 rebase/merge 或复制规则 |
| `/Users/mentianlu/.codex/worktrees/record-main-d8b65fe7-deploy/umanews` | `ec727d79ddf3b266469c30bfbf5c9d3371d212c1` | `codex/record-main-d8b65fe7-deploy` | main deploy record（名称关联） | unknown | 停在发布证据点；重读 main/显式消息、查旧 skills，再 rebase/merge 或复制规则 |
| `/Users/mentianlu/.codex/worktrees/release-three-changes/umanews` | `7372d2c4c834c858e39024ec37519bf15281b094` | `codex/release-three-changes` | three changes release（名称关联） | unknown | 停在发布安全点并交接三 change 状态；重读 main/显式消息、查旧 skills，再 rebase/merge 或复制规则 |
| `/Users/mentianlu/.codex/worktrees/umanews-archive-all-latest` | `80454c6b02c2ab6ce0ac02d2c007ada884013ed1` | `codex/archive-all-latest` | archive all latest（名称关联） | unknown | 停在归档边界；重读 main/显式消息并检查旧 archive skill，再 rebase/merge 或复制新规则 |
| `/Users/mentianlu/code/umanews/.claude/worktrees/blissful-northcutt-85b019` | `e2e3e0752b4f7b76c62128e4b49bcf60bbd222e0` | detached | unknown | unknown | 恢复先确认 Claude detached task/分支并停安全点；重读 main/显式消息、查旧 skills，再选分支同步规则 |
| `/Users/mentianlu/code/umanews/.claude/worktrees/gracious-babbage-406f83` | `7123e4e5736126fb0d7cd62097f3da8e7d7b88c8` | detached | unknown | unknown | 恢复先确认 Claude detached task/分支并停安全点；重读 main/显式消息、查旧 skills，再选分支同步规则 |
| `/Users/mentianlu/Code/umanews/.worktrees/multiregion-v3-audit-performance` | `e04dcd23240c7c9afecd0c7e4384465f7301a313` | `codex/multiregion-v3-audit-performance` | multiregion V3 audit（名称关联） | unknown | 冻结性能/Gold 证据后停点；重读 main/显式消息、查旧 skills，再 rebase/merge 或复制规则 |
| `/Users/mentianlu/Code/umanews/.worktrees/news-sponichi-prod-hotfix` | `8321138c49888c8543602277195d07e5d25d4697` | `codex/news-sponichi-prod-hotfix` | Sponichi prod hotfix（名称关联） | unknown | 停在翻译/发布队列安全点并交接计数；重读 main/显式消息、查旧 skills，再 rebase/merge 或复制规则 |
| `/Users/mentianlu/Code/umanews/.worktrees/next-step-review-20260715` | `d6d6f58b2b5b90301d8fa633a650df28379c09e7` | `codex/next-step-review-20260715` | `codex-native-workflow-migration` | 方案 reviewer 已 APPROVED；代码 reviewer REVISE；尚未发布 | 完成三项 finding 候选修复后回到同一代码 reviewer 会话，仅复审修复与直接路径；通过后等待用户授权，不做发布 |
| `/Users/mentianlu/Code/umanews/runtime/race_event_crawl_runs/dev-worktrees/historical-progress-guard` | `d6d6f58b2b5b90301d8fa633a650df28379c09e7` | `codex/fix-historical-exhausted-region-progress` | 历史进度 guard（名称关联） | unknown | 原子 runner 安全停点后交接 lease/IDs/结果；重读 main/显式消息、查旧 skills，再 rebase/merge 或复制规则 |
<!-- WORKFLOW_CONTRACT:WORKTREE_INVENTORY:END -->

对全部旧 worktree 的共同约束是“不直接覆写”。恢复时必须先停在其业务安全检查点，读取
共享 main 的新规则和用户给该 task 的显式消息，检查仍可发现的旧 skills；随后按该
worktree 的冲突/历史情况选择 rebase、merge，或把新规则复制到在途分支并纳入其完整
review。不能仅因目录仍存在就推断 task active，也不能为迁移整齐而重做生产操作。

## 本机 `.claude` ignored 副本

根工作区的五个 `.claude/skills/openspec-*` 是本机 ignored 副本，不属于 Git 交付。本轮已
将它们完整软删除到 `/Users/mentianlu/Code/umanews/.claude/disabled-skills/2026-07-15/`，逐文件
验证字节 SHA-256 与 `0644` 权限不变，并确认原 `.claude/skills/openspec-*` 不再存在。该本机动作
仅防止旧 Claude skill 被本地发现；共享规则由 tracked `AGENTS.md`、工作流文档和
`.codex/skills` allowlist 承担，不能把本机 move 描述为已随 Git 发布。

## 发布前验收

- 本需求方案 reviewer 已按限定范围复审并返回 `APPROVED`；代码 reviewer 当前仍为 `REVISE`，
  三项 actionable finding 正在修复，修复后回到同一代码 reviewer 会话复审。
- 当前验收目标为 fingerprint `24/24`、transition/index `10/10`、workflow contract tests
  `26/26` 和当前仓库 checker 全绿；通过测试不等于代码 review 已通过。
- reviewer agent 配置同步方案/代码 reviewer 会话复用、不可恢复交接和具体漏洞复审范围；
  canonical 文件不得残留“每轮全新 reviewer”旧规则。
- active skill 仅 `grill-me-codex`、`plan-eng-review`、`tdd`；禁用 skills 不在发现路径。
- 14 个 tracked legacy archive 文件固定 SHA/权限且非 symlink；本机 `.claude` 五个副本
  move 后逐文件字节/权限一致。
- 同一代码 reviewer 会话仅复审 staging freeze、外部 filter 和状态文档三项修复及直接路径；
  在 reviewer 明确通过前保持 `REVISE`。
- 仍保持未 commit、未 push、未部署、未写生产；等待最新成功 review 后用户当前任务授权。

future durable 生效仍依次等待：同一代码 reviewer 会话完成三项 finding 复审且 actionable
findings 清零、用户在最新成功代码 review 后针对当前任务给出发布授权、提交并合入共享 main。
