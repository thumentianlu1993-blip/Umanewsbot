# add-netkeiba-horse-client 发布报告

## task 5.3 无写入候选

- 执行日期：2026-07-24（Asia/Shanghai）
- 生产版本：`4972a6b2eb35167d5783f5c37908b8b3d190160d`
- 审查：`APPROVED`，P0/P1/P2=`0/0/0`，session
  `019f9095-2025-7a80-96be-b50800b18d82`
- 批次：`p0batch-20b59bda0608`
- 原审核工作簿 SHA-256：
  `bee158e6d70c099c550102df6f9221b2d6bbb5fb75697d50a06d6d87b61cbc9f`
- 批次批准 SHA-256：
  `51ac349ebd45848abb89c9f29545e695a760d245e09e72fcecc0de4bfaefa44f`

### 冻结对象与绑定

- 完整对象：61；blocker：39；artifact/blocker 交集：0。
- research：
  `1afce80f871cc703e0527113bc4f33db06766770029ebf380444b77108fb115b`
- mapping：
  `e96c8aa9a2fa965f9cc18b0b5931bc47af48f882d8c3833ef9b35a2fe414e826`
- authority：
  `759ac2dcdcbff1c22f62424f7c6167c417ae99d9d669c14a0ef0fa38ab1f7bdb`
- combined candidates：
  `6975c975c662ae6fd1bc8711f2ded68a9c71818d4c79de411208eb07fdadf50d`
- production snapshot：
  `0e0ad3dcf447912d5de6d19714c10e67862b3cd4b327274706da6338e5c45733`
- commit artifact：
  `1abbf475927c1e4391ab1ce851b3cd28958da2ec65641c28ec4f49e9608c4894`
- release candidate：
  `8ef0f718803f7772db5b498925a71651e5c68cb331aeafa50f03dc831f8848fe`

### 预计动作与公开范围

- profile creates：0
- profile updates：61
- race record creates：1,490
- race record updates：0
- P0 source upserts：61
- module audits：244
- 自动首发：0
- 已公开且跳过首发：61
- 新身份：0

### 零写入验收

- 重复 prepare-release 的 candidate 文件字节和 SHA 一致。
- approvals ledger 保持 3 行；`release_candidate_prepared=1`、
  `release_approved=0`；未生成 v2 release manifest。
- HorseProfile、HorseP0Source、HorseRaceRecord、HorseProfileCompletionRun、
  OperationLog 和公开计数均与执行前一致。
- 宿主和 `web / worker / beat / race_live_worker` 的
  `HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=false`。
- 未运行 `--commit`、`--retry-publish`，也未传 `--approved-by`。

当前停在 task 5.4 前。正式写入必须取得针对 release candidate
`8ef0f718803f7772db5b498925a71651e5c68cb331aeafa50f03dc831f8848fe`
的新授权。

## task 5.4 首次正式写入结果

- 用户已授权上述 candidate，批准人 `mentianlu`；生成的 v2 release manifest SHA-256 为
  `5320c33c44d387b14e827b109353ffe5068d997bd9c62d9df903cb5de91e0c90`。
- 数据库 apply 在 `イエローマジック` 的 strict-complete 复验处 fail closed，原因是该马真实
  无胜场，而当前完整度逻辑不能区分“major-wins 未审核”和“已审核确认暂无胜绩”。
- 61 行中有 10 匹真实无胜场；不得为通过门禁而虚构胜场。
- PostgreSQL 事务整批回滚；马匹业务表、completion run、OperationLog 和公开计数均零变化，
  自动首发未运行，网络保持 false。
- task 5.4 未完成。建议通过新测试锁定“approved empty major-wins”语义，实施窄修并独立复审；
  部署后重新生成 candidate，任何新 SHA 都必须重新授权。

## task 5.4 空胜绩门禁本地修复

- 用户已授权开始修复；生产仍保持网络 false，且本轮没有连接、读取或写入生产。
- 修复后只有最新非 ignored 的 `major_wins` 候选为 applied、审核为 approved、payload 精确为空
  且带执行人/执行时间，才表示“已审核确认无胜绩”；无审核、非空 payload 或最新 conflict
  仍保留 blocker。
- artifact 与 candidate 新增
  `completion_policy_version=p0-horse-full-profile-completeness.v2`，旧 candidate
  `8ef0f718...` 会在 DB 前拒绝，不能复用旧批准。
- 关键 RED→GREEN 3 项通过。P0/完整度组合 312 项中 308 项通过；4 项旧公开页面文案失败已在
  修复前 `04c89e35` 基线全部复现，增量失败为 0。
- 排除已确认基线失败后，P0 production apply/batch 246 项与三项新增完整度回归合计 `249/249`
  通过；
  Django check、迁移检查、旧规格流程 strict/all `37/37`、diff check 均通过。
- 独立审查提出的两项 P1 已修复并补回归：非空 applied payload 不得作为无胜绩证据；新策略
  只在 v2 发布链路强制，历史 v1 artifact 保留只读复验能力。
- 后续直接路径复审发现的 v1 commit 和手工 ready 问题也已 RED→GREEN：可信 v1 只能 dry-run，
  commit 在写库前拒绝；无胜绩手工审核继续写空列表证据。
- 当前等待同一独立 review 会话确认。仓库门禁要求在最新成功 review 后重新取得当前任务发布
  授权；review 前的持续授权不替代该门禁。范围漂移仍必须停步。

## task 5.4 最终发布结果

- 最终 review：`APPROVED / no findings`；指纹
  `257b68c30e8c4ce304826edd0551adb768f4c8cd7d11d17eb244a9a651601d59`。
- 提交/镜像：`044f3d57f4f3bb75eac31f0567917132e5ae5cff` /
  `sha256:01f0fd3466873b0a1c44bb7ad4ab5d64d4a8f0e2e9d8a5a6df84a27dfad8861d`。
- candidate/artifact/release：
  `6dc853a2b5581de3af241fca81fb76d0f48bcea600abcb7c231206d229a69f9b` /
  `b1e123fa77387505a1380b6ae932712117c68aa8aef502deb66b149d25838863` /
  `8c6f2dc8d88abce2d432b3e3d174611dedbba2f5a04f174e17d1376365c1511d`。
- 实际结果：61 profile updates、1,490 record creates、244 module audits、61 P0 source creates、
  1 completion run、0 profile creates、0 publish。61 匹均 strict complete；10 匹无记录胜绩
  由 approved empty 证据满足门禁。
- 相同 candidate 普通重放 planned remaining 全 0，数据库计数不变；61 个公开详情页、HTTP
  healthz、日本马匹列表与四应用 network false 通过。
